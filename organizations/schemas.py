from dataclasses import dataclass


"""
@dataclass is a decorator that automatically generates special methods like __init__() and __repr__() for classes that are primarily used to store data.
Defines data transfer objects (DTOs) for user registration, login, email verification, 
email change, password change, and account deletion. These DTOs are used to structure 
and validate the data received from forms before processing it in views or services."""

@dataclass
class CreateOrganizationDTO:
    name: str # name of the organization to be created
    created_by_id: int # user ID of the creator

    #runs after the dataclass is initialized to clean up whitespace and validate the organization name
    def __post_init__(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Organization name cannot be empty.")
        if len(self.name) > 150:
            raise ValueError("Organization name cannot exceed 150 characters.")

@dataclass
class UpdateOrganizationDTO:
    organization_id: int # ID of the organization to be updated
    acting_user_id: int # ID of the user performing the update (must be owner or admin)
    name: str # new name for the organization

    #runs after the dataclass is initialized to clean up whitespace and validate the organization name
    def __post_init__(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Organization name cannot be empty.")
        if len(self.name) > 150:
            raise ValueError("Organization name cannot exceed 150 characters.")

@dataclass
class InviteMemberDTO:
    organization_id: int # ID of the organization to which the member is being invited
    acting_user_id: int # the user performing the invite (must be owner or admin)
    target_username: str # the user being invited
    role: str = "member"

    #runs after the dataclass is initialized to clean up whitespace and validate the target username and role
    def __post_init__(self):
        self.target_username = self.target_username.strip()
        valid_roles = {"owner", "admin", "member"}
        if self.role not in valid_roles:
            raise ValueError(f"Invalid role. Must be one of: {', '.join(valid_roles)}")


@dataclass
class RespondToInviteDTO:
    acting_user_id: int # ID of the user responding (must be the invited user)
    invite_uuid: str # UUID of the OrganizationInvite being responded to
    accept: bool # True = accept the invite, False = reject it

    # runs after the dataclass is initialized to normalise the UUID to a string
    def __post_init__(self):
        self.invite_uuid = str(self.invite_uuid).strip()
        if not self.invite_uuid:
            raise ValueError("Invite UUID cannot be empty.")

@dataclass
class GenerateInviteLinkDTO:
    acting_user_id: int # ID of the user generating the link (must be owner or admin)
    organization_id: int # ID of the organization the link belongs to


@dataclass
class DisableInviteLinkDTO:
    acting_user_id: int # ID of the user disabling the link (must be owner or admin)
    organization_id: int # ID of the organization whose link is being disabled

@dataclass
class ProcessLinkJoinDTO:
    token: str # UUID of the InviteLink the user clicked
    user_id: int # ID of the user requesting to join

    # runs after the dataclass is initialized to normalise the token to a string
    def __post_init__(self):
        self.token = str(self.token).strip()
        if not self.token:
            raise ValueError("Invite link token cannot be empty.")


@dataclass
class RespondToJoinRequestDTO:
    acting_user_id: int # ID of the admin/owner handling the request
    join_request_uuid: str # UUID of the LinkJoinRequest being handled
    approve: bool # True = approve and create membership, False = reject

    # runs after the dataclass is initialized to normalise the UUID to a string
    def __post_init__(self):
        self.join_request_uuid = str(self.join_request_uuid).strip()
        if not self.join_request_uuid:
            raise ValueError("Join request UUID cannot be empty.")

@dataclass
class TransferOwnershipDTO:
    acting_user_id: int # ID of the current owner performing the transfer
    organization_id: int # ID of the organization whose ownership is being transferred
    target_membership_uuid: str # UUID of the membership that will become the new owner

    # runs after the dataclass is initialized to normalise the UUID to a string
    def __post_init__(self):
        self.target_membership_uuid = str(self.target_membership_uuid).strip()
        if not self.target_membership_uuid:
            raise ValueError("Target membership UUID cannot be empty.")

@dataclass
class RemoveMemberDTO:
    organization_id: int # ID of the organization from which the member is being removed
    acting_user_id: int # who is performing the removal
    target_membership_uuid: str # which membership is being removed


@dataclass
class ChangeMemberRoleDTO:
    organization_id: int # ID of the organization in which the role change is happening
    acting_user_id: int # who is performing the role change (must be owner)
    target_membership_uuid: str # which membership is having its role changed
    new_role: str # the new role to assign (must be "owner", "admin", or "member")

    # runs after the dataclass is initialized to validate the new role
    def __post_init__(self):
        valid_roles = {"owner", "admin", "member"}
        if self.new_role not in valid_roles:
            raise ValueError(f"Invalid role. Must be one of: {', '.join(valid_roles)}")


@dataclass
class DeleteOrganizationDTO:
    organization_id: int # ID of the organization to be deleted
    acting_user_id: int # who is performing the deletion (must be owner)