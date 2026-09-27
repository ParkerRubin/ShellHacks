from .models import FaceSignature, Presence, UserProfile


class ConsentManager:
    def __init__(self, store, presence, identifier):
        self.store, self.presence, self.identifier = store, presence, identifier

    def remember(self, confirmed=False, name=None):
        # "false" and 1 must never be interpreted as spoken consent.
        if confirmed is not True:
            return "Ask permission to store conversations and a face signature and use them for personalization."
        try:
            with self.identifier.lock:
                signature = self.identifier.current_signature
                if signature is None:
                    return "I cannot enroll you yet. Face recognition must be available and one face must be visible."
                if self.presence.user_id:
                    return "You are already remembered."
                profile = UserProfile(
                    display_name=str(name)[:100] if name else None,
                    consents={
                        "store_personal_data": True,
                        "store_face_data": True,
                        "use_for_personalization": True,
                    },
                )
                user_id = self.store.store_user_profile(profile)
                if not user_id:
                    return "I could not save your consent. Please try again."
                if not self.store.associate_face(
                    FaceSignature(signature, user_id), user_id
                ):
                    self.store.delete_user_data(user_id)
                    return "I could not enroll your face. Please try again."
                current = self.presence.get()
                self.presence.set(
                    Presence(user_id, True, True, True, True, current.generation)
                )
                self.identifier.previous_match = user_id
                return "I will remember you. Say forget me to delete your saved data."
        except Exception:
            return "I could not save your consent. Please try again."

    def forget(self):
        try:
            with self.identifier.lock:
                user_id = self.presence.user_id
                if not user_id:
                    return "I do not have a recognized profile to delete. An operator can delete a profile by its ID."
                report = self.store.delete_user_data(user_id)
                self.identifier.clear()
                if report.remote_pending:
                    return "Your local data is deleted and personalization stopped. Atlas deletion is queued until synchronization completes."
                return "Your saved data has been deleted."
        except Exception:
            self.identifier.clear()
            return "Personalization has stopped, but deletion could not be completed. Please ask the operator to retry."
