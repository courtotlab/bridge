from app.models.mapping import MappingAlternative, SingleMappingRequest, SingleMappingResponse


def map_single_term(request: SingleMappingRequest) -> SingleMappingResponse:
    return SingleMappingResponse(
        source_term=request.source_term,
        target_code="HP:0012735",
        target_term="Cough",
        ontology="HPO",
        confidence=0.94,
        notes="Mock result for prototype. Replace with real llm-ontology-mapper integration later.",
        alternatives=[
            MappingAlternative(
                code="HP:0002099",
                term="Asthma",
                ontology="HPO",
                confidence=0.61,
            ),
        ],
    )
