from fastapi import APIRouter

from app.models.mapping import SingleMappingRequest, SingleMappingResponse
from app.services.mapper_service import map_single_term

router = APIRouter()


@router.post("/single", response_model=SingleMappingResponse)
def map_single(request: SingleMappingRequest) -> SingleMappingResponse:
    return map_single_term(request)
