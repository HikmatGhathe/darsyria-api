from sqlalchemy import Column, String, DateTime, func

from app.database import Base


class AppSetting(Base):
    """Admin-tunable runtime settings as simple key/value rows.

    Lets an admin flip behavior (e.g. whether listings require payment) without
    a redeploy. Values are stored as strings; callers coerce via
    app.services.settings_service.
    """

    __tablename__ = "app_settings"

    key = Column(String(80), primary_key=True)
    value = Column(String(500), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<AppSetting {self.key}={self.value!r}>"
