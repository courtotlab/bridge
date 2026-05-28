import logging

from fastapi import APIRouter, HTTPException

from app.models.validator import ValidateCodeRequest, ValidateResponse
from app.services.validate_service import validate_codes

router = APIRouter()
logger = logging.getLogger(__name__)

_MAX_CODES = 200


@router.post("", response_model=ValidateResponse)
async def validate(request: ValidateCodeRequest) -> ValidateResponse:
    codes = [c.strip() for c in request.codes if c.strip()]

    if len(codes) > _MAX_CODES:
        raise HTTPException(
            status_code=422,
            detail=f"Too many codes: {len(codes)} submitted, maximum is {_MAX_CODES}.",
        )
    if not codes:
        return ValidateResponse(results=[])

    logger.info("[validate] checking %d codes", len(codes))
    results = await validate_codes(codes)
    valid_count = sum(1 for r in results if r.status == "valid")
    logger.info(
        "[validate] done — %d valid / %d not-found / %d deprecated",
        valid_count,
        sum(1 for r in results if r.status == "not-found"),
        sum(1 for r in results if r.status == "deprecated"),
    )
    return ValidateResponse(results=results)
