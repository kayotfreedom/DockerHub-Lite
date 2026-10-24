from pydantic import BaseModel


class CloneRequest(BaseModel):
    clone_url: str
    name: str


class BuildRequest(BaseModel):
    repo_name: str
    dockerfile_path: str = "Dockerfile"
    target: str | None = None


class RunScriptRequest(BaseModel):
    repo_name: str
    script_path: str


class InstallDepsRequest(BaseModel):
    repo_name: str
    requirements_path: str = "requirements.txt"


class StopRequest(BaseModel):
    repo_name: str