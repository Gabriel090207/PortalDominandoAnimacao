"""Manual resumption delegates eligibility and audit to one transaction."""
class AdminResumptionService:
    def __init__(self,repository):self.repository=repository

    def resume(self,customer_id,administrator):
        return self.repository.resume(customer_id,administrator)
