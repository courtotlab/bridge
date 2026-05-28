from typing import Literal

from pydantic import BaseModel


class ValidateCodeRequest(BaseModel):
    codes: list[str]


class ValidateResult(BaseModel):
    code: str
    status: Literal["valid", "not-found", "deprecated"]
    term: str | None = None
    ontology: str | None = None


class ValidateResponse(BaseModel):
    results: list[ValidateResult]
