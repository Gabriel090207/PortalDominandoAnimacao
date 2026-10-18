"""Manual decision coordination; eligibility and audit commit atomically."""
class AdminSuspensionService:
    def __init__(self,repository):self.repository=repository

    def suspend(self,customer_id,administrator):
        return self.repository.suspend(customer_id,administrator)
