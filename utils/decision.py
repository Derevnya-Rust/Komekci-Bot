
from typing import NamedTuple, List, Optional


class NickCheckResult(NamedTuple):
    """Результат проверки никнейма"""
    approve: bool
    public_reasons: List[str] = []
    fixed_full: Optional[str] = None
    
    @property
    def reasons(self) -> List[str]:
        """Синоним для public_reasons для совместимости"""
        return self.public_reasons


class ValidationResult(NamedTuple):
    """Результат валидации"""
    success: bool
    message: str = ""
    data: dict = {}
from typing import List, Optional


class NickCheckResult:
    """Результат проверки никнейма"""
    
    def __init__(self, approve: bool, reasons: List[str] = None, fixed_full: str = None, notes_to_user: str = ""):
        self.approve = approve
        self.reasons = reasons or []
        self.fixed_full = fixed_full
        self.notes_to_user = notes_to_user
    
    def __bool__(self):
        """Позволяет использовать объект в условных выражениях"""
        return self.approve
    
    def __str__(self):
        status = "✅ Одобрен" if self.approve else "❌ Отклонен"
        return f"NickCheckResult({status}, reasons={len(self.reasons)})"
    
    def __repr__(self):
        return self.__str__()
