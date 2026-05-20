import logging

import requests.exceptions
from fastapi import APIRouter, HTTPException

from app.models.mapping import SingleMappingRequest, SingleMappingResponse
from app.services.mapper_service import map_single_term

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/single", response_model=SingleMappingResponse)
def map_single(request: SingleMappingRequest) -> SingleMappingResponse:
    logger.info(
        "[map/single] term='%s' entity_type='%s' ontologies='%s'",
        request.source_term,
        request.entity_type,
        request.target_ontologies,
    )

    try:
        result = map_single_term(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (RuntimeError, ImportError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except requests.exceptions.Timeout as exc:
        raise HTTPException(
            status_code=503,
            detail="The search timed out. Try again or check that your AI provider is running.",
        ) from exc
    except requests.exceptions.ConnectionError as exc:
        raise HTTPException(
            status_code=503,
            detail="Could not reach the AI provider — check your connection settings and try again.",
        ) from exc

    latency = result.metadata.latency_ms if result.metadata else None
    logger.info(
        "[map/single] result → code='%s' confidence=%s logic_type='%s' latency=%sms",
        result.target_code,
        result.confidence,
        result.logic_type,
        latency,
    )

    return result
