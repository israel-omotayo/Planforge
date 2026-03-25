from dataclasses import dataclass
from typing import Optional


@dataclass
class CreateTaskDTO:
    project_id: int
    created_by_id: int
    title: str
    description: str = ""
    status: str = "todo"
    priority: str = "medium"
    due_date: Optional[str] = None      # "YYYY-MM-DD" string or None
    assigned_to_id: Optional[int] = None

    def __post_init__(self):
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("Task title cannot be empty.")
        if len(self.title) > 50:
            raise ValueError("Task title cannot exceed 50 characters.")
        valid_statuses = {"todo", "in_progress", "done"}
        if self.status not in valid_statuses:
            raise ValueError(f"Invalid status. Must be one of: {', '.join(valid_statuses)}")
        valid_priorities = {"low", "medium", "high"}
        if self.priority not in valid_priorities:
            raise ValueError(f"Invalid priority. Must be one of: {', '.join(valid_priorities)}")


@dataclass
class UpdateTaskDTO:
    task_uuid: str
    acting_user_id: int
    project_id: int
    title: str
    description: str = ""
    status: str = "todo"
    priority: str = "medium"
    due_date: Optional[str] = None
    assigned_to_id: Optional[int] = None

    def __post_init__(self):
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("Task title cannot be empty.")
        if len(self.title) > 50:
            raise ValueError("Task title cannot exceed 50 characters.")
        valid_statuses = {"todo", "in_progress", "done"}
        if self.status not in valid_statuses:
            raise ValueError(f"Invalid status. Must be one of: {', '.join(valid_statuses)}")
        valid_priorities = {"low", "medium", "high"}
        if self.priority not in valid_priorities:
            raise ValueError(f"Invalid priority. Must be one of: {', '.join(valid_priorities)}")


@dataclass
class DeleteTaskDTO:
    task_uuid: str
    acting_user_id: int
    project_id: int


@dataclass
class UpdateTaskStatusDTO:
    """Lightweight DTO for quick status toggle (mark done / reopen)."""
    task_uuid: str
    acting_user_id: int
    project_id: int
    status: str

    def __post_init__(self):
        valid_statuses = {"todo", "in_progress", "done"}
        if self.status not in valid_statuses:
            raise ValueError(f"Invalid status. Must be one of: {', '.join(valid_statuses)}")


@dataclass
class InviteGuestDTO:
    project_id: int
    invited_by_id: int
    email: str

    def __post_init__(self):
        self.email = self.email.strip().lower()
        if not self.email:
            raise ValueError("Email address is required.")


@dataclass
class AcceptGuestInviteDTO:
    invite_uuid: str
    accepting_user_id: int