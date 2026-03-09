from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from app.schemas.models import JobRecord


class FileJobRepository:
    def __init__(self) -> None:
        self._jobs_dir = get_settings().jobs_dir
        self._jobs_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, job_id: str) -> Path:
        return self._jobs_dir / f"{job_id}.json"

    def save(self, job: JobRecord) -> JobRecord:
        path = self.path_for(job.job_id)
        path.write_text(job.model_dump_json(indent=2), encoding="utf-8")
        return job

    def get(self, job_id: str) -> JobRecord:
        path = self.path_for(job_id)
        return JobRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def exists(self, job_id: str) -> bool:
        return self.path_for(job_id).exists()

    def list_jobs(self) -> list[JobRecord]:
        jobs: list[JobRecord] = []
        for path in sorted(self._jobs_dir.glob("*.json")):
            try:
                jobs.append(JobRecord.model_validate_json(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        return jobs
