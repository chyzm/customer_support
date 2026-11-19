from pydantic import BaseModel, Field


class TicketRequest(BaseModel):
    """What a client sends us. Limits keep oversized input away from the provider."""

    subject: str = Field(min_length=3, max_length=200)
    message: str = Field(min_length=10, max_length=5000)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "subject": "Payment processing failure",
                    "message": (
                        "We have been unable to process customer payments since "
                        "yesterday. Every transaction returns an error, and our "
                        "business operations are being affected."
                    ),
                }
            ]
        }
    }
