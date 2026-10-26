"""
NoSQL Database Layer for E-Commerce Product and Customer Analytics System.
Provides a unified interface with automatic dual-mode operation:
1. Real MongoDB via PyMongo when a connection string / active MongoDB server is detected.
2. High-performance JSON Document Store with complete MongoDB Query & Aggregation Pipeline engine ($match, $group, $sort, $project, $lookup, $unwind, $limit, $skip, $sum, $avg, etc.) when running standalone.
"""

import os
import json
import re
import copy
import uuid
import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "db.json"

class JSONEncoderHelper(json.JSONEncoder):
    """Custom JSON encoder to handle datetime, UUID, and custom types."""
    def default(self, obj):
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        if isinstance(obj, uuid.UUID):
            return str(obj)
        return super().default(obj)

def matches_condition(doc_val: Any, cond_val: Any) -> bool:
    """Evaluate MongoDB filter condition."""
    if isinstance(cond_val, dict):
        for op, target in cond_val.items():
            if op == "$eq" and doc_val != target:
                return False
            elif op == "$ne" and doc_val == target:
                return False
            elif op == "$gt" and not (doc_val is not None and doc_val > target):
                return False
            elif op == "$gte" and not (doc_val is not None and doc_val >= target):
                return False
            elif op == "$lt" and not (doc_val is not None and doc_val < target):
                return False
            elif op == "$lte" and not (doc_val is not None and doc_val <= target):
                return False
            elif op == "$in" and doc_val not in target:
                return False
            elif op == "$nin" and doc_val in target:
                return False
            elif op == "$regex":
                pattern = target
                if not isinstance(pattern, str) or not doc_val:
                    return False
                if not re.search(pattern, str(doc_val), re.IGNORECASE):
                    return False
        return True
    return doc_val == cond_val

def filter_document(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    """Check if a document matches a MongoDB-style query filter."""
    if not query:
        return True
    
    for key, val in query.items():
        if key == "$and":
            if not all(filter_document(doc, subq) for subq in val):
                return False
        elif key == "$or":
            if not any(filter_document(doc, subq) for subq in val):
                return False
        elif key == "$nor":
            if any(filter_document(doc, subq) for subq in val):
                return False
        else:
            # Handle nested key (e.g. "address.city")
            parts = key.split(".")
            curr = doc
            for p in parts:
                if isinstance(curr, dict) and p in curr:
                    curr = curr[p]
                else:
                    curr = None
                    break
            if not matches_condition(curr, val):
                return False
    return True

class LocalCollection:
    """MongoDB Collection emulation supporting CRUD and Aggregation Pipelines."""
    def __init__(self, name: str, store: 'LocalDocumentStore'):
        self.name = name
        self.store = store

    def _get_docs(self) -> List[Dict[str, Any]]:
        return self.store.data.get(self.name, [])

    def find(self, query: Optional[Dict[str, Any]] = None, projection: Optional[Dict[str, Any]] = None, sort: Optional[List] = None, limit: Optional[int] = None, skip: Optional[int] = 0) -> List[Dict[str, Any]]:
        docs = [copy.deepcopy(d) for d in self._get_docs() if filter_document(d, query or {})]
        
        if sort:
            for field, direction in reversed(sort):
                docs.sort(key=lambda x: (x.get(field) is None, x.get(field)), reverse=(direction < 0))
        
        if skip:
            docs = docs[skip:]
        if limit:
            docs = docs[:limit]

        if projection:
            include_keys = [k for k, v in projection.items() if v == 1 and k != "_id"]
            exclude_keys = [k for k, v in projection.items() if v == 0]
            include_id = projection.get("_id", 1) == 1

            projected = []
            for doc in docs:
                new_doc = {}
                if include_keys:
                    for k in include_keys:
                        if k in doc:
                            new_doc[k] = doc[k]
                    if include_id and "_id" in doc:
                        new_doc["_id"] = doc["_id"]
                elif exclude_keys:
                    new_doc = {k: v for k, v in doc.items() if k not in exclude_keys}
                else:
                    new_doc = doc
                projected.append(new_doc)
            return projected

        return docs

    def find_one(self, query: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        results = self.find(query, limit=1)
        return results[0] if results else None

    def insert_one(self, document: Dict[str, Any]) -> Dict[str, Any]:
        doc = copy.deepcopy(document)
        if "_id" not in doc:
            doc["_id"] = f"{self.name[:3]}_{uuid.uuid4().hex[:8]}"
        self._get_docs().append(doc)
        self.store.save()
        return doc

    def insert_many(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        inserted = []
        for d in documents:
            doc = copy.deepcopy(d)
            if "_id" not in doc:
                doc["_id"] = f"{self.name[:3]}_{uuid.uuid4().hex[:8]}"
            self._get_docs().append(doc)
            inserted.append(doc)
        self.store.save()
        return inserted

    def update_one(self, query: Dict[str, Any], update: Dict[str, Any]) -> bool:
        docs = self._get_docs()
        for i, d in enumerate(docs):
            if filter_document(d, query):
                if "$set" in update:
                    for k, v in update["$set"].items():
                        parts = k.split(".")
                        target = d
                        for p in parts[:-1]:
                            target = target.setdefault(p, {})
                        target[parts[-1]] = v
                if "$inc" in update:
                    for k, v in update["$inc"].items():
                        d[k] = d.get(k, 0) + v
                if "$push" in update:
                    for k, v in update["$push"].items():
                        arr = d.setdefault(k, [])
                        if isinstance(arr, list):
                            arr.append(v)
                self.store.save()
                return True
        return False

    def delete_one(self, query: Dict[str, Any]) -> bool:
        docs = self._get_docs()
        for i, d in enumerate(docs):
            if filter_document(d, query):
                docs.pop(i)
                self.store.save()
                return True
        return False

    def count_documents(self, query: Optional[Dict[str, Any]] = None) -> int:
        return len(self.find(query))

    def aggregate(self, pipeline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Executes MongoDB Aggregation Pipeline ($match, $group, $sort, $project, $lookup, $unwind, $limit, $skip, $count)."""
        current_docs = [copy.deepcopy(d) for d in self._get_docs()]

        for stage in pipeline:
            stage_name = list(stage.keys())[0]
            stage_val = stage[stage_name]

            if stage_name == "$match":
                current_docs = [d for d in current_docs if filter_document(d, stage_val)]

            elif stage_name == "$lookup":
                from_coll = stage_val.get("from")
                local_f = stage_val.get("localField")
                foreign_f = stage_val.get("foreignField")
                as_field = stage_val.get("as")
                target_docs = self.store.data.get(from_coll, [])

                for doc in current_docs:
                    local_val = doc.get(local_f)
                    matches = [copy.deepcopy(td) for td in target_docs if td.get(foreign_f) == local_val]
                    doc[as_field] = matches

            elif stage_name == "$unwind":
                path = stage_val if isinstance(stage_val, str) else stage_val.get("path")
                field_name = path.lstrip("$")
                unwound = []
                for doc in current_docs:
                    arr = doc.get(field_name, [])
                    if isinstance(arr, list) and arr:
                        for item in arr:
                            cloned = copy.deepcopy(doc)
                            cloned[field_name] = item
                            unwound.append(cloned)
                    else:
                        if isinstance(stage_val, dict) and stage_val.get("preserveNullAndEmptyArrays"):
                            cloned = copy.deepcopy(doc)
                            cloned[field_name] = None
                            unwound.append(cloned)
                current_docs = unwound

            elif stage_name == "$group":
                grouped: Dict[Any, List[Dict[str, Any]]] = {}
                id_spec = stage_val.get("_id")

                for doc in current_docs:
                    # Resolve group key
                    if id_spec is None:
                        key = None
                    elif isinstance(id_spec, str) and id_spec.startswith("$"):
                        key = doc.get(id_spec[1:])
                    elif isinstance(id_spec, dict):
                        key = tuple((k, doc.get(v[1:] if isinstance(v, str) and v.startswith("$") else v)) for k, v in sorted(id_spec.items()))
                    else:
                        key = id_spec
                    
                    grouped.setdefault(key, []).append(doc)

                result_docs = []
                for key, docs_in_group in grouped.items():
                    res = {}
                    if isinstance(key, tuple):
                        res["_id"] = dict(key)
                    else:
                        res["_id"] = key

                    for field_name, acc in stage_val.items():
                        if field_name == "_id":
                            continue
                        acc_op = list(acc.keys())[0]
                        acc_val = acc[acc_op]

                        if acc_op == "$sum":
                            if isinstance(acc_val, (int, float)):
                                res[field_name] = len(docs_in_group) * acc_val
                            elif isinstance(acc_val, str) and acc_val.startswith("$"):
                                f = acc_val[1:]
                                res[field_name] = sum(float(d.get(f) or 0) for d in docs_in_group)
                        elif acc_op == "$avg":
                            if isinstance(acc_val, str) and acc_val.startswith("$"):
                                f = acc_val[1:]
                                vals = [float(d.get(f)) for d in docs_in_group if d.get(f) is not None]
                                res[field_name] = round(sum(vals) / len(vals), 2) if vals else 0
                        elif acc_op == "$count":
                            res[field_name] = len(docs_in_group)
                        elif acc_op == "$min":
                            if isinstance(acc_val, str) and acc_val.startswith("$"):
                                f = acc_val[1:]
                                vals = [d.get(f) for d in docs_in_group if d.get(f) is not None]
                                res[field_name] = min(vals) if vals else None
                        elif acc_op == "$max":
                            if isinstance(acc_val, str) and acc_val.startswith("$"):
                                f = acc_val[1:]
                                vals = [d.get(f) for d in docs_in_group if d.get(f) is not None]
                                res[field_name] = max(vals) if vals else None
                        elif acc_op == "$push":
                            if isinstance(acc_val, str) and acc_val.startswith("$"):
                                f = acc_val[1:]
                                res[field_name] = [d.get(f) for d in docs_in_group]
                            elif acc_val == "$$ROOT":
                                res[field_name] = docs_in_group
                        elif acc_op == "$addToSet":
                            if isinstance(acc_val, str) and acc_val.startswith("$"):
                                f = acc_val[1:]
                                res[field_name] = list({d.get(f) for d in docs_in_group if d.get(f) is not None})
                    result_docs.append(res)
                current_docs = result_docs

            elif stage_name == "$project":
                projected = []
                for doc in current_docs:
                    new_doc = {}
                    for k, spec in stage_val.items():
                        if spec == 1:
                            if k in doc:
                                new_doc[k] = doc[k]
                        elif spec == 0:
                            pass
                        elif isinstance(spec, str) and spec.startswith("$"):
                            new_doc[k] = doc.get(spec[1:])
                        elif isinstance(spec, dict):
                            # Simple expressions like $multiply, $concat
                            if "$multiply" in spec:
                                factors = spec["$multiply"]
                                total = 1.0
                                for fac in factors:
                                    if isinstance(fac, str) and fac.startswith("$"):
                                        total *= float(doc.get(fac[1:], 0) or 0)
                                    else:
                                        total *= float(fac)
                                new_doc[k] = round(total, 2)
                            else:
                                new_doc[k] = spec
                        else:
                            new_doc[k] = spec
                    if "_id" not in stage_val and "_id" in doc:
                        new_doc["_id"] = doc["_id"]
                    projected.append(new_doc)
                current_docs = projected

            elif stage_name == "$sort":
                for field, direction in reversed(list(stage_val.items())):
                    current_docs.sort(
                        key=lambda x: (x.get(field) is None, x.get(field)),
                        reverse=(direction < 0)
                    )

            elif stage_name == "$limit":
                current_docs = current_docs[:int(stage_val)]

            elif stage_name == "$skip":
                current_docs = current_docs[int(stage_val):]

            elif stage_name == "$count":
                current_docs = [{stage_val: len(current_docs)}]

        return current_docs

class LocalDocumentStore:
    """Local In-Memory & JSON file-backed NoSQL Document Database."""
    def __init__(self, filepath: Path = DATA_FILE):
        self.filepath = filepath
        self.data: Dict[str, List[Dict[str, Any]]] = {
            "customers": [],
            "products": [],
            "orders": [],
            "transactions": [],
            "analytics_logs": []
        }
        self.collections: Dict[str, LocalCollection] = {}
        self.load()

    def load(self):
        if self.filepath.exists():
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    for k in self.data.keys():
                        self.data[k] = loaded.get(k, [])
            except Exception as e:
                print(f"[NoSQL Engine] Warning loading {self.filepath}: {e}")
        else:
            self.save()

    def save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, cls=JSONEncoderHelper)

    def get_collection(self, name: str) -> LocalCollection:
        if name not in self.collections:
            if name not in self.data:
                self.data[name] = []
            self.collections[name] = LocalCollection(name, self)
        return self.collections[name]

    def reset_data(self, new_data: Dict[str, List[Dict[str, Any]]]):
        self.data = copy.deepcopy(new_data)
        self.save()

class DatabaseManager:
    """Unified NoSQL manager supporting MongoDB with automatic fallback."""
    def __init__(self):
        self.mode = "local" # "mongodb" or "local"
        self.mongo_client = None
        self.mongo_db = None
        self.local_store = LocalDocumentStore()
        self.connect()

    def connect(self, uri: Optional[str] = None):
        mongo_uri = uri or os.environ.get("MONGODB_URI", "")
        if mongo_uri:
            try:
                import pymongo
                client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
                client.server_info() # test ping
                self.mongo_client = client
                db_name = os.environ.get("MONGODB_DB", "ecommerce_analytics")
                self.mongo_db = client[db_name]
                self.mode = "mongodb"
                print(f"[NoSQL Engine] Connected to real MongoDB at {mongo_uri}")
                return True
            except Exception as e:
                print(f"[NoSQL Engine] MongoDB connection failed ({e}). Defaulting to embedded Local NoSQL Document Engine.")
        
        self.mode = "local"
        return False

    def get_collection(self, name: str):
        if self.mode == "mongodb" and self.mongo_db is not None:
            return self.mongo_db[name]
        return self.local_store.get_collection(name)

    def status(self) -> Dict[str, Any]:
        coll_counts = {}
        for c in ["customers", "products", "orders", "transactions"]:
            try:
                coll_counts[c] = self.get_collection(c).count_documents({})
            except Exception:
                coll_counts[c] = 0
        return {
            "mode": self.mode,
            "engine": "MongoDB Atlas / Server" if self.mode == "mongodb" else "Embedded JSON Document Store (BSON Aggregation Engine)",
            "counts": coll_counts,
            "storage_path": str(self.local_store.filepath) if self.mode == "local" else "Remote MongoDB"
        }

# Global DB Instance
db = DatabaseManager()
