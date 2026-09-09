from server.crud.base import CRUDBase
from server.db.models import FaqTable
from server.schemas.faq import FaqCreate, FaqUpdate


class CRUDFaq(CRUDBase[FaqTable, FaqCreate, FaqUpdate]):
    def get_by_question(self, question: str):
        return FaqTable.query.filter(FaqTable.question == question).first()

    def get_duplicate_question(self, question: str, faq_id: str):
        return FaqTable.query.filter(FaqTable.question == question, FaqTable.id != faq_id).first()


faq_crud = CRUDFaq(FaqTable)
