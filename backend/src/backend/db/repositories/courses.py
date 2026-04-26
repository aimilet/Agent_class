from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.errors import DomainError
from backend.domain.models import Course, CourseEnrollment, Person, RosterCandidateRow, RosterImportBatch


class CourseRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, *, course_code: str, course_name: str, term: str, class_label: str, teacher_name: str | None) -> Course:
        existing = self.session.scalar(
            select(Course).where(
                Course.course_code == course_code,
                Course.term == term,
                Course.class_label == class_label,
            )
        )
        if existing is not None:
            raise DomainError("课程已存在。", code="course_exists", status_code=409)
        course = Course(
            public_id=Course.build_public_id(),
            course_code=course_code,
            course_name=course_name,
            term=term,
            class_label=class_label,
            teacher_name=teacher_name,
        )
        self.session.add(course)
        self.session.flush()
        return course

    def get_by_public_id(self, course_public_id: str) -> Course:
        course = self.session.scalar(select(Course).where(Course.public_id == course_public_id))
        if course is None:
            raise DomainError("课程不存在。", code="course_not_found", status_code=404)
        return course

    def list_all(self) -> list[Course]:
        return list(self.session.scalars(select(Course).order_by(Course.created_at.desc())).all())


class RosterRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_batch(self, course: Course, *, source_files_json: list[dict], parse_mode: str) -> RosterImportBatch:
        batch = RosterImportBatch(
            public_id=RosterImportBatch.build_public_id(),
            course_id=course.id,
            source_files_json=source_files_json,
            parse_mode=parse_mode,
        )
        self.session.add(batch)
        self.session.flush()
        return batch

    def get_batch(self, batch_public_id: str) -> RosterImportBatch:
        batch = self.session.scalar(select(RosterImportBatch).where(RosterImportBatch.public_id == batch_public_id))
        if batch is None:
            raise DomainError("名单批次不存在。", code="roster_batch_not_found", status_code=404)
        return batch

    def list_candidates(self, batch: RosterImportBatch) -> list[RosterCandidateRow]:
        return list(
            self.session.scalars(
                select(RosterCandidateRow)
                .where(RosterCandidateRow.batch_id == batch.id)
                .order_by(RosterCandidateRow.created_at.asc())
            ).all()
        )

    def replace_candidates(self, batch: RosterImportBatch, candidates: list[dict]) -> list[RosterCandidateRow]:
        for row in self.list_candidates(batch):
            self.session.delete(row)
        created: list[RosterCandidateRow] = []
        for item in candidates:
            row = RosterCandidateRow(
                public_id=RosterCandidateRow.build_public_id(),
                batch_id=batch.id,
                source_file=item["source_file"],
                page_no=item.get("page_no"),
                row_ref=item.get("row_ref"),
                student_no=item.get("student_no"),
                name=item["name"],
                confidence=item.get("confidence", 0.0),
                raw_fragment=item.get("raw_fragment"),
                decision_status=item.get("decision_status", "pending"),
                decision_note=item.get("decision_note"),
            )
            self.session.add(row)
            created.append(row)
        self.session.flush()
        return created


class EnrollmentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_by_course(self, course: Course) -> list[CourseEnrollment]:
        return list(
            self.session.scalars(
                select(CourseEnrollment)
                .where(CourseEnrollment.course_id == course.id)
                .order_by(CourseEnrollment.display_name.asc())
            ).all()
        )

    def get_by_public_id(self, enrollment_public_id: str) -> CourseEnrollment:
        enrollment = self.session.scalar(select(CourseEnrollment).where(CourseEnrollment.public_id == enrollment_public_id))
        if enrollment is None:
            raise DomainError("课程名单不存在。", code="enrollment_not_found", status_code=404)
        return enrollment

    def upsert_person(self, *, student_no: str | None, name: str) -> Person:
        student_no_norm = (student_no or "").strip() or None
        name_norm = name.strip().lower()
        person = None
        if student_no_norm:
            person = self.session.scalar(select(Person).where(Person.student_no_norm == student_no_norm))
        if person is None:
            person = self.session.scalar(select(Person).where(Person.name_norm == name_norm))
        if person is None:
            person = Person(
                public_id=Person.build_public_id(),
                student_no_raw=student_no,
                student_no_norm=student_no_norm,
                name_raw=name,
                name_norm=name_norm,
            )
            self.session.add(person)
            self.session.flush()
            return person
        person.student_no_raw = student_no or person.student_no_raw
        person.student_no_norm = student_no_norm or person.student_no_norm
        person.name_raw = name
        person.name_norm = name_norm
        self.session.flush()
        return person

    def apply_roster(self, course: Course, batch: RosterImportBatch, candidates: list[RosterCandidateRow]) -> list[CourseEnrollment]:
        created: list[CourseEnrollment] = []
        existing_by_person = {
            enrollment.person_id: enrollment for enrollment in self.list_by_course(course)
        }
        for candidate in candidates:
            if candidate.decision_status == "rejected":
                continue
            person = self.upsert_person(student_no=candidate.student_no, name=candidate.name)
            enrollment = existing_by_person.get(person.id)
            if enrollment is None:
                enrollment = CourseEnrollment(
                    public_id=CourseEnrollment.build_public_id(),
                    course_id=course.id,
                    person_id=person.id,
                    display_student_no=candidate.student_no,
                    display_name=candidate.name,
                    source_roster_batch_id=batch.id,
                    status="active",
                )
                self.session.add(enrollment)
                created.append(enrollment)
                existing_by_person[person.id] = enrollment
            else:
                enrollment.display_student_no = candidate.student_no
                enrollment.display_name = candidate.name
                enrollment.source_roster_batch_id = batch.id
                enrollment.status = "active"
        self.session.flush()
        return created
