from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    UNI_USERNAME: str = Field(default="")
    UNI_PASSWORD: str = Field(default="")
    CAMPUS_LOGIN_URL: str = Field(
        default="https://matricula.upf.edu/cosmos/Controlador/?apl=Uninavs&gu=a&idNav=inicio&NuevaSesionUsuario=true&NombreUsuarioAlumno=ALUMNO&responsive=S"
    )
    SECRETARIA_AJAX_URL: str = Field(
        default="https://secretariavirtual.upf.edu/pds/control/[Ajax]selecionarRangoHorarios?rnd=4236.0&start={start}&end={end}"
    )
    GOOGLE_SERVICE_ACCOUNT_KEY: str = Field(default="")
    GOOGLE_CALENDAR_ID: str = Field(default="")
    TELEGRAM_BOT_TOKEN: str = Field(default="")
    TELEGRAM_CHAT_ID: str = Field(default="")
    TIMEZONE: str = Field(default="Europe/Madrid")
    HEADLESS_BROWSER: bool = Field(default=True)
    TRACE_DIR: str = Field(default="artifacts/traces")
    SUBJECT_GROUP_FILTERS: str = Field(default="")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
