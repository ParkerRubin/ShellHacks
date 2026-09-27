from .models import now
from .schemas import validate


class MongoStore:
    def __init__(self, database):
        self.db = database

    def put(self, collection, doc):
        validate(collection, doc)
        self.db[collection].replace_one({"_id": doc["_id"]}, doc, upsert=True)

    def get(self, collection, record_id):
        return self.db[collection].find_one({"_id": record_id})

    def list(self, collection, user_id=None, limit=100, all_users=False):
        query = {} if all_users else {"user_id": user_id}
        if collection == "interactions":
            query["expires_at"] = {"$gt": now()}
        return list(self.db[collection].find(query).sort("timestamp", -1).limit(limit))

    def search(self, query, user_id, vector=None, limit=30):
        privacy = {
            "user_id": {"$eq": user_id},
            "privacy_level": {"$in": ["public", "personal"]},
        }
        if vector is not None:
            pipeline = [
                {
                    "$vectorSearch": {
                        "index": "interactions_vec",
                        "path": "embedding",
                        "queryVector": vector,
                        "numCandidates": max(100, limit * 10),
                        "limit": limit,
                        "filter": privacy,
                    }
                },
                {"$set": {"similarity": {"$meta": "vectorSearchScore"}}},
            ]
        else:
            pipeline = [
                {
                    "$search": {
                        "index": "interactions_text",
                        "text": {
                            "query": query,
                            "path": ["context.topics", "context.entities"],
                        },
                    }
                },
                {"$match": privacy},
                {"$limit": limit},
                {"$set": {"similarity": {"$meta": "searchScore"}}},
            ]
        pipeline.append({"$match": {"expires_at": {"$gt": now()}}})
        return list(self.db.interactions.aggregate(pipeline, maxTimeMS=150))

    def delete_user_data(self, user_id):
        count = self.db.user_profiles.delete_many({"_id": user_id}).deleted_count
        for collection in ("interactions", "face_signatures"):
            count += self.db[collection].delete_many({"user_id": user_id}).deleted_count
        return count
