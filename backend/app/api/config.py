from fastapi import APIRouter

from app.models.config import ConfigTestRequest, ConfigTestResponse

router = APIRouter()


@router.post("/test", response_model=ConfigTestResponse)
def test_config(request: ConfigTestRequest) -> ConfigTestResponse:
    ontologies = ", ".join(request.selected_ontologies) if request.selected_ontologies else "none"
    return ConfigTestResponse(
        success=True,
        message=(
            f"Mock connection accepted. Provider: {request.provider}, "
            f"model: {request.model}, ontologies: {ontologies}. "
            "Real provider testing will be added when llm-ontology-mapper is integrated."
        ),
    )
