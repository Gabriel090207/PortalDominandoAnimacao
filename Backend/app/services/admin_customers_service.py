"""Read-only customer consultation; permissions enforced by HTTP dependency."""
from app.domain.admin_customers import AdminPurchaseConfirmation, customer_identifier

class AdminCustomersService:
    def __init__(self, repository):
        self.repository=repository

    def list_customers(self, *, limit=20, cursor=None):
        return self.repository.list_page(limit=limit,cursor=cursor)


    def get_customer(self, customer_id):
        return self.repository.get_by_id(customer_id)

    def purchase_confirmation(self, customer_id):
        identifier=customer_identifier(customer_id)
        if self.repository.get_by_id(identifier) is None:
            return None
        return AdminPurchaseConfirmation(customer_id=identifier,
            approved_purchase_recorded=self.repository.has_approved_purchase(identifier))

    def lookup_customer(self, email):
        return self.repository.find_by_email(email)
