from pydantic import BaseModel, ConfigDict, Field


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginIn(Base):
    email: str = Field(min_length=3, max_length=254)
    clave: str = Field(min_length=1, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshIn(Base):
    refresh_token: str = Field(min_length=20, max_length=200)


class CambioClaveIn(Base):
    actual: str = Field(min_length=1, max_length=256)
    nueva: str = Field(min_length=1, max_length=256)


class UsuarioIn(Base):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    nombre: str = Field(min_length=1, max_length=200)
    clave: str = Field(min_length=1, max_length=256)


class RolAsignacionIn(Base):
    rol: str = Field(min_length=1, max_length=60)
    departamento_id: int | None = None     # nulo = todos los departamentos


class PerfilOut(BaseModel):
    id: int
    email: str
    nombre: str
    permisos: dict[str, list[int | None]]
