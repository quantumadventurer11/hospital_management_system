"""Typed in-memory repositories used by the demo services."""
from __future__ import annotations
from typing import Any, Dict, Generic, Iterable, List, TypeVar
try:
    from typing import Protocol, runtime_checkable
except Exception:
    from typing_extensions import Protocol, runtime_checkable  # type: ignore
from .domain import (Patient, Doctor, Department, Appointment, MedicalRecord,
                     BillingAccount, Bed, InsuranceProvider, InsurancePolicy)
from .errors import DuplicateError, NotFoundError

T = TypeVar('T')

# -----------------------------
# Repositories (in-memory)
# -----------------------------
@runtime_checkable
class Repo(Protocol[T]):
    """CRUD contract used by services to interact with persistence layers."""

    def get(self, obj_id: str) -> T: ...

    def add(self, obj: T) -> T: ...

    def update(self, obj: T) -> T: ...

    def find(self, **filters: Any) -> List[T]: ...

    def all(self) -> Iterable[T]: ...


class MemoryRepo(Generic[T]):
    """Simple in-memory repository used for interactive demo flows."""

    def __init__(self, key: str):
        self._key = key
        self._data: Dict[str, T] = {}

    @property
    def key(self) -> str:
        """Identifier attribute this repository indexes on."""
        return self._key

    def get(self, obj_id: str) -> T:
        if obj_id not in self._data:
            raise NotFoundError(f"{self._key} not found: {obj_id}")
        return self._data[obj_id]

    def add(self, obj: T) -> T:
        oid = getattr(obj, self._key)
        if oid in self._data:
            raise DuplicateError(f"{self._key} exists: {oid}")
        self._data[oid] = obj
        return obj

    def update(self, obj: T) -> T:
        oid = getattr(obj, self._key)
        if oid not in self._data:
            raise NotFoundError(f"{self._key} not found: {oid}")
        self._data[oid] = obj
        return obj

    def all(self) -> Iterable[T]:
        return tuple(self._data.values())

    def find(self, **filters: Any) -> List[T]:
        results: List[T] = []
        for value in self._data.values():
            if all(getattr(value, field) == expected for field, expected in filters.items()):
                results.append(value)
        return results

# Typed repos
class PatientRepo(MemoryRepo[Patient]):
    def __init__(self): super().__init__("patient_id")
class DoctorRepo(MemoryRepo[Doctor]):
    def __init__(self): super().__init__("doctor_id")
class DepartmentRepo(MemoryRepo[Department]):
    def __init__(self): super().__init__("dept_id")
class AppointmentRepo(MemoryRepo[Appointment]):
    def __init__(self): super().__init__("appt_id")
class RecordRepo(MemoryRepo[MedicalRecord]):
    def __init__(self): super().__init__("record_id")
class BillingRepo(MemoryRepo[BillingAccount]):
    def __init__(self): super().__init__("acct_id")
class BedRepo(MemoryRepo[Bed]):
    def __init__(self): super().__init__("bed_id")
class InsuranceProviderRepo(MemoryRepo[InsuranceProvider]):
    def __init__(self): super().__init__("provider_id")
class PolicyRepo(MemoryRepo[InsurancePolicy]):
    def __init__(self): super().__init__("policy_id")
