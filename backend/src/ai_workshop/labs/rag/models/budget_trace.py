"""Body-free, bounded metadata from the actual context admission check."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

BudgetConstraint = Literal["groups", "units", "characters"]


class BudgetTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    incoming_units: int = Field(strict=True, ge=0)
    incoming_characters: int = Field(strict=True, ge=0)
    before_groups: int = Field(strict=True, ge=0)
    before_units: int = Field(strict=True, ge=0)
    before_characters: int = Field(strict=True, ge=0)
    group_limit: int = Field(strict=True, gt=0)
    unit_limit: int = Field(strict=True, gt=0)
    character_limit: int = Field(strict=True, gt=0)
    violated: tuple[BudgetConstraint, ...] = Field(max_length=3)

    @model_validator(mode="after")
    def unique_constraints(self) -> Self:
        if len(set(self.violated)) != len(self.violated):
            raise ValueError("Budget constraints must be unique.")
        return self
