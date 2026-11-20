"""认证请求模型（E2-T03 / T04）。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

CLIENT_ID_PATTERN = r"^cli_[a-z0-9]{12}$"
CHALLENGE_ID_PATTERN = r"^chl_[a-z0-9]{12}$"
PROOF_PATTERN = r"^[A-Za-z0-9_-]{43}$"


class ChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(pattern=CLIENT_ID_PATTERN)


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: str = Field(pattern=CHALLENGE_ID_PATTERN)
    client_id: str = Field(pattern=CLIENT_ID_PATTERN)
    proof: str = Field(pattern=PROOF_PATTERN)
