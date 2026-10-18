"""Manual decision coordination; eligibility and audit commit atomically."""
class AdminActivationService:
    def __init__(self,repository):self.repository=repository

    def activate(self,customer_id,administrator):
        return self.repository.activate(customer_id,administrator)
