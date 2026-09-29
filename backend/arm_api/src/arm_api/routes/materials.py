"""
GET    /materials                - список (справочная база для обучающегося)
POST   /materials                - загрузка файла (multipart/form-data)
GET    /materials/{id}/download  - выгрузка файла
DELETE /materials/{id}           - удаление неактуального материала
POST   /materials/{id}/index     - разобрать материал на фрагменты для ИИ (база знаний)
GET    /materials/search?q=      - поиск по базе знаний (что увидит ИИ при генерации)
"""

import hashlib
import os
import re
import uuid as uuid_mod
from datetime import datetime, timezone

from flask import Blueprint, current_app, request, send_file
from sqlalchemy import select

from ..core.errors import ApiError
from ..core.extensions import db
from ..core.pagination import paginate
from ..core.security import current_user, is_student, require, write_audit
from ..models import IncidentCategory, Material
from ..services import knowledge
from ._helpers import commit, get_or_404, int_arg, item, ok

materials_bp = Blueprint("materials", __name__)

ALLOWED_MIME = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/json": "json",
    "text/csv": "csv",
    "text/xml": "xml",
    "application/xml": "xml",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "text/plain": "txt",
}


def _download_name(material):
    """Название материала + расширение вместо технического имени на диске."""
    extension = os.path.splitext(material.file_path)[1]
    title = re.sub(r'[\\/:*?"<>|\r\n]+', "_", material.title).strip(" .") or "material"
    return title if title.lower().endswith(extension.lower()) else title + extension


@materials_bp.get("/materials")
def list_materials():
    principal = current_user()
    stmt = select(Material).order_by(Material.created_at.desc())
    if int_arg("category_id") is not None:
        stmt = stmt.where(Material.category_id == int_arg("category_id"))
    if is_student(principal) and principal.service_scope:
        scope = [c.id for c in principal.service_scope]
        stmt = stmt.where(Material.category_id.in_(scope + [None]))
    return ok(paginate(stmt))


@materials_bp.post("/materials")
def upload_material():
    principal = require("material.manage")
    upload = request.files.get("file")
    if upload is None:
        raise ApiError("Файл не передан (поле file, multipart/form-data)", 422)

    title = (request.form.get("title") or upload.filename or "").strip()
    if not title:
        raise ApiError("Не указано название материала (поле title)", 422)

    mime = upload.mimetype or "application/octet-stream"
    if mime not in ALLOWED_MIME:
        raise ApiError(
            "Неподдерживаемый формат файла",
            422,
            details={"allowed": sorted(set(ALLOWED_MIME.values()))},
        )

    # тип файла из заголовка запроса подделать легко, сверяем его с расширением
    extension = os.path.splitext(upload.filename or "")[1].lower().lstrip(".")
    if extension != ALLOWED_MIME[mime]:
        raise ApiError(
            f"Расширение файла не соответствует его типу (ожидается .{ALLOWED_MIME[mime]})",
            422,
        )

    category_id = request.form.get("category_id")
    if category_id:
        try:
            category_id = int(category_id)
        except ValueError:
            raise ApiError("category_id должен быть целым числом", 422)
        get_or_404(IncidentCategory, category_id, "Категория")
    else:
        category_id = None

    base_dir = current_app.config["MATERIALS_DIR"]
    os.makedirs(base_dir, exist_ok=True)
    # имя на диске не зависит от загруженного: русские названия secure_filename стирает
    stored_name = f"{uuid_mod.uuid4().hex}.{ALLOWED_MIME[mime]}"
    path = os.path.join(base_dir, stored_name)

    digest = hashlib.sha256()
    size = 0
    with open(path, "wb") as fh:
        while chunk := upload.stream.read(1024 * 256):
            digest.update(chunk)
            size += len(chunk)
            fh.write(chunk)

    previous = (
        db.session.execute(
            select(Material)
            .where(Material.title == title)
            .order_by(Material.version.desc())
        )
        .scalars()
        .first()
    )

    material = Material(
        title=title,
        mime_type=mime,
        file_path=path,
        size_bytes=size,
        checksum=digest.hexdigest(),
        version=(previous.version + 1) if previous else 1,
        category_id=category_id,
        uploaded_by=principal.id,
        is_indexed=False,
    )
    db.session.add(material)
    db.session.flush()
    chunks = _index(material)
    write_audit(
        db.session,
        request,
        principal,
        "material.upload",
        "material",
        material.id,
        {"size_bytes": size, "mime": mime, "chunks": chunks},
    )
    commit()
    return item(material, 201)


def _index(material):
    """Индексация для ИИ: is_indexed выставляется, только если нашелся текст."""
    chunks = knowledge.index_material(material)
    material.is_indexed = chunks > 0
    material.indexed_at = datetime.now(timezone.utc) if chunks else None
    return chunks


@materials_bp.post("/materials/<uuid:material_id>/index")
def index_material(material_id):
    principal = require("material.manage")
    material = get_or_404(Material, material_id, "Материал")
    chunks = _index(material)
    write_audit(
        db.session,
        request,
        principal,
        "material.index",
        "material",
        material.id,
        {"chunks": chunks},
    )
    commit()
    return ok({**material.to_dict(), "chunks": chunks})


@materials_bp.get("/materials/search")
def search_materials():
    require("material.manage")
    query = (request.args.get("q") or "").strip()
    if len(query) < 2:
        raise ApiError("Запрос q не короче 2 символов", 422)
    category_id = int_arg("category_id")
    limit = min(max(int_arg("limit") or 4, 1), 20)
    return ok({"items": knowledge.search(query, category_id, limit)})


@materials_bp.get("/materials/<uuid:material_id>/download")
def download_material(material_id):
    principal = current_user()
    material = get_or_404(Material, material_id, "Материал")
    if is_student(principal) and principal.service_scope and material.category_id:
        if material.category_id not in {c.id for c in principal.service_scope}:
            raise ApiError("Материал недоступен для вашего профиля событий", 403)
    if not os.path.exists(material.file_path):
        raise ApiError("Файл материала отсутствует на диске", 404)
    return send_file(
        material.file_path,
        mimetype=material.mime_type,
        as_attachment=True,
        download_name=_download_name(material),
    )


@materials_bp.delete("/materials/<uuid:material_id>")
def delete_material(material_id):
    principal = require("material.manage")
    material = get_or_404(Material, material_id, "Материал")
    try:
        os.remove(material.file_path)
    except OSError:
        current_app.logger.warning("Файл материала %s уже удален", material.file_path)
    db.session.delete(material)
    write_audit(
        db.session, request, principal, "material.delete", "material", material_id
    )
    commit()
    return ok({"status": "deleted"})
