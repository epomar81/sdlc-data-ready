"""Shared validation for data crossing application ports."""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from story_slicer.domain.models import DomainModel

Provider = Literal["gemini", "nvidia", "openai"]
NonNegativeInteger = Annotated[int, Field(ge=0)]
PositiveInteger = Annotated[int, Field(gt=0)]
ElapsedSeconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]
PositiveSeconds = Annotated[float, Field(gt=0, allow_inf_nan=False)]
ErrorRate = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class ContractModel(DomainModel):
    """Immutable boundary objects; mutable nested data must be treated as read-only."""

    model_config = ConfigDict(frozen=True)
