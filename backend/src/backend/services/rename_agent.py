from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypedDict
from uuid import uuid4

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from backend.config import Settings, get_settings
from backend.models import Student
from backend.services.llm_utils import extract_json, stringify_content
from backend.services.rename_service import RenameOperation, RenameRuleSpec, preview_renames


TOKEN_SPLIT_RE = re.compile(r"[_\-\s]+")
PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")
ALIAS_MAP: dict[str, tuple[str, ...]] = {
    "assignment": ("作业", "assignment", "题目", "任务", "实验", "project", "homework"),
    "class_name": ("班级", "class", "教学班"),
    "student_no": ("学号", "student_no", "student id", "studentid", "id"),
    "name": ("姓名", "名字", "学生姓名", "name"),
    "original_stem": ("原文件名", "原始文件名", "原文件", "文件名", "original", "原名"),
}


@dataclass(slots=True)
class RenamePatternSummary:
    style_key: str
    count: int
    description: str
    examples: list[str]


@dataclass(slots=True)
class RenamePlanResult:
    template: str
    notes: list[str]


@dataclass(slots=True)
class RenameAgentPreview:
    directory_path: str
    naming_rule: str
    normalized_template: str
    detected_patterns: list[RenamePatternSummary]
    items: list[RenameOperation]
    script_path: str
    script_content: str
    notes: list[str]


class NamingPatternAgent(Protocol):
    def analyze(self, files: list[Path]) -> list[RenamePatternSummary]: ...


class RenameRulePlannerAgent(Protocol):
    def plan(self, naming_rule: str) -> RenamePlanResult: ...


class HeuristicNamingPatternAgent:
    def analyze(self, files: list[Path]) -> list[RenamePatternSummary]:
        buckets: dict[str, list[str]] = {}
        for file_path in files:
            style_key = self._style_key(file_path.stem)
            buckets.setdefault(style_key, []).append(file_path.name)

        summaries: list[RenamePatternSummary] = []
        for style_key, names in sorted(buckets.items(), key=lambda item: (-len(item[1]), item[0])):
            summaries.append(
                RenamePatternSummary(
                    style_key=style_key,
                    count=len(names),
                    description=self._describe_style(style_key, names),
                    examples=names[:5],
                )
            )
        return summaries

    def _style_key(self, stem: str) -> str:
        stripped = stem.strip()
        if not stripped:
            return "empty"

        separator = self._detect_separator(stripped)
        parts = [part for part in TOKEN_SPLIT_RE.split(stripped) if part] if separator else [stripped]
        token_types = [self._token_type(part) for part in parts]
        joiner = separator or "none"
        return f"{joiner}|{'-'.join(token_types)}|parts:{len(parts)}"

    def _detect_separator(self, stem: str) -> str:
        if "_" in stem:
            return "underscore"
        if "-" in stem:
            return "hyphen"
        if " " in stem:
            return "space"
        return ""

    def _token_type(self, token: str) -> str:
        if token.isdigit():
            return "digits"
        if re.fullmatch(r"[A-Za-z]+", token):
            return "letters"
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            return "cjk"
        if re.search(r"\d", token) and re.search(r"[A-Za-z]", token):
            return "alnum"
        if re.search(r"\d", token) and re.search(r"[\u4e00-\u9fff]", token):
            return "mixed-cjk-digit"
        return "mixed"

    def _describe_style(self, style_key: str, names: list[str]) -> str:
        separator, token_key, part_key = style_key.split("|", 2)
        separator_text = {
            "underscore": "下划线分隔",
            "hyphen": "横杠分隔",
            "space": "空格分隔",
            "none": "无明显分隔符",
        }.get(separator, separator)
        return f"{separator_text}，{part_key.replace('parts:', '')} 段命名，类型序列：{token_key}。样例数 {len(names)}。"


class HeuristicRenameRulePlannerAgent:
    def plan(self, naming_rule: str) -> RenamePlanResult:
        direct_template = self._extract_direct_template(naming_rule)
        if direct_template:
            return RenamePlanResult(template=direct_template, notes=["已直接使用用户给出的模板表达式。"])

        separator = self._detect_separator(naming_rule)
        ordered_fields = self._extract_ordered_fields(naming_rule)
        if not ordered_fields:
            ordered_fields = ["assignment", "student_no", "name"]

        template = separator.join(f"{{{field}}}" for field in ordered_fields)
        return RenamePlanResult(
            template=template,
            notes=[
                "已按自然语言规则推断规范模板。",
                f"字段顺序：{', '.join(ordered_fields)}",
                f"连接符：{separator!r}",
            ],
        )

    def _extract_direct_template(self, naming_rule: str) -> str | None:
        if "{" in naming_rule and "}" in naming_rule:
            return naming_rule.strip()
        return None

    def _detect_separator(self, naming_rule: str) -> str:
        lowered = naming_rule.lower()
        if "横杠" in naming_rule or "连字符" in naming_rule or "-" in naming_rule:
            return "-"
        if "空格" in naming_rule:
            return " "
        if "下划线" in naming_rule or "_" in naming_rule:
            return "_"
        return "_"

    def _extract_ordered_fields(self, naming_rule: str) -> list[str]:
        lowered = naming_rule.lower()
        indexed: list[tuple[int, str]] = []
        for field, aliases in ALIAS_MAP.items():
            positions = [lowered.find(alias.lower()) for alias in aliases if lowered.find(alias.lower()) >= 0]
            if positions:
                indexed.append((min(positions), field))
        indexed.sort(key=lambda item: item[0])
        return [field for _, field in indexed]


class OpenAICompatibleRenameRulePlannerAgent:
    def __init__(self, settings: Settings, fallback: RenameRulePlannerAgent) -> None:
        self.fallback = fallback
        self.client = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0,
        )

    def plan(self, naming_rule: str) -> RenamePlanResult:
        prompt = (
            "你是改名规则规划 Agent。请把用户给出的规范命名要求转换成一个 Python format 模板。"
            "可用字段仅有：assignment、class_name、student_no、name、original_stem。"
            "只返回 JSON，格式为："
            '{"template":"{assignment}_{student_no}_{name}","notes":["..."]}\n\n'
            f"用户规则：\n{naming_rule}"
        )
        try:
            response = self.client.invoke(prompt)
            payload = extract_json(stringify_content(response.content))
            template = str(payload.get("template", "")).strip()
            notes = [str(item) for item in payload.get("notes", []) if str(item).strip()]
            if template and self._template_is_supported(template):
                return RenamePlanResult(template=template, notes=notes or ["已由大模型转换模板。"])
        except Exception:
            pass
        return self.fallback.plan(naming_rule)

    def _template_is_supported(self, template: str) -> bool:
        allowed = set(ALIAS_MAP)
        placeholders = {item.strip() for item in PLACEHOLDER_RE.findall(template)}
        return bool(template) and placeholders.issubset(allowed)


class RenameWorkflowState(TypedDict, total=False):
    directory_path: str
    naming_rule: str
    assignment_label: str | None
    files: list[Path]
    students: list[Student]
    detected_patterns: list[RenamePatternSummary]
    normalized_template: str
    notes: list[str]
    items: list[RenameOperation]
    script_path: str
    script_content: str


class RenameAgentWorkflow:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.pattern_agent: NamingPatternAgent = HeuristicNamingPatternAgent()
        heuristic_planner = HeuristicRenameRulePlannerAgent()
        if self.settings.llm_enabled:
            self.rule_agent: RenameRulePlannerAgent = OpenAICompatibleRenameRulePlannerAgent(
                self.settings,
                heuristic_planner,
            )
        else:
            self.rule_agent = heuristic_planner

        graph = StateGraph(RenameWorkflowState)
        graph.add_node("scan_files", self._scan_files)
        graph.add_node("analyze_patterns", self._analyze_patterns)
        graph.add_node("plan_template", self._plan_template)
        graph.add_node("build_preview", self._build_preview)
        graph.add_node("render_script", self._render_script)
        graph.add_edge(START, "scan_files")
        graph.add_edge("scan_files", "analyze_patterns")
        graph.add_edge("analyze_patterns", "plan_template")
        graph.add_edge("plan_template", "build_preview")
        graph.add_edge("build_preview", "render_script")
        graph.add_edge("render_script", END)
        self.graph = graph.compile()

    def analyze_directory(self, directory_path: str) -> tuple[str, list[RenamePatternSummary], list[str]]:
        scanned = self._scan_files({"directory_path": directory_path})
        analyzed = self._analyze_patterns(
            {
                "directory_path": directory_path,
                "files": scanned["files"],
                "notes": scanned["notes"],
            }
        )
        return (
            str(Path(directory_path).expanduser().resolve()),
            list(analyzed["detected_patterns"]),
            list(analyzed["notes"]),
        )

    def build_preview(
        self,
        *,
        directory_path: str,
        naming_rule: str,
        students: list[Student],
        assignment_label: str | None = None,
    ) -> RenameAgentPreview:
        state = self.graph.invoke(
            {
                "directory_path": directory_path,
                "naming_rule": naming_rule,
                "students": students,
                "assignment_label": assignment_label,
            }
        )
        return RenameAgentPreview(
            directory_path=str(Path(state["directory_path"]).expanduser().resolve()),
            naming_rule=naming_rule,
            normalized_template=state["normalized_template"],
            detected_patterns=list(state["detected_patterns"]),
            items=list(state["items"]),
            script_path=state["script_path"],
            script_content=state["script_content"],
            notes=list(state["notes"]),
        )

    def execute_script(self, script_path: str) -> dict[str, Any]:
        resolved = Path(script_path).expanduser().resolve()
        allowed_root = (self.settings.artifacts_root / "rename_scripts").resolve()
        if allowed_root not in resolved.parents:
            raise ValueError("脚本路径不在受控目录中。")
        if not resolved.exists():
            raise ValueError("改名脚本不存在。")

        completed = subprocess.run(
            [sys.executable, str(resolved), "--apply"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise ValueError(completed.stderr.strip() or completed.stdout.strip() or "改名脚本执行失败。")
        return json.loads(completed.stdout)

    def _scan_files(self, state: RenameWorkflowState) -> dict[str, Any]:
        directory = Path(state["directory_path"]).expanduser().resolve()
        if not directory.is_dir():
            raise ValueError("改名目录不存在，或不是文件夹。")
        files = sorted(path for path in directory.iterdir() if path.is_file())
        if not files:
            raise ValueError("改名目录下没有可处理文件。")
        return {"files": files, "notes": [f"共扫描到 {len(files)} 个文件。"]}

    def _analyze_patterns(self, state: RenameWorkflowState) -> dict[str, Any]:
        patterns = self.pattern_agent.analyze(state["files"])
        notes = list(state.get("notes", []))
        notes.append(f"识别到 {len(patterns)} 类命名风格。")
        return {"detected_patterns": patterns, "notes": notes}

    def _plan_template(self, state: RenameWorkflowState) -> dict[str, Any]:
        plan = self.rule_agent.plan(state["naming_rule"])
        notes = list(state.get("notes", []))
        notes.extend(plan.notes)
        return {"normalized_template": plan.template, "notes": notes}

    def _build_preview(self, state: RenameWorkflowState) -> dict[str, Any]:
        spec = RenameRuleSpec(
            template=state["normalized_template"],
            assignment_label_default=state.get("assignment_label"),
            match_threshold=76.0,
        )
        items = preview_renames(
            state["directory_path"],
            spec,
            state.get("students", []),
            state.get("assignment_label"),
        )
        notes = list(state.get("notes", []))
        notes.append("已根据规范命名规则生成改名预览。")
        return {"items": items, "notes": notes}

    def _render_script(self, state: RenameWorkflowState) -> dict[str, Any]:
        script_root = self.settings.artifacts_root / "rename_scripts"
        script_root.mkdir(parents=True, exist_ok=True)
        script_path = script_root / f"rename_agent_{uuid4().hex}.py"
        operations_payload = [item.as_dict() for item in state["items"]]
        script_content = self._build_script_content(operations_payload)
        script_path.write_text(script_content, encoding="utf-8")
        return {
            "script_path": str(script_path),
            "script_content": script_content,
        }

    def _build_script_content(self, operations_payload: list[dict[str, Any]]) -> str:
        payload_text = json.dumps(operations_payload, ensure_ascii=False, indent=2)
        return f"""from __future__ import annotations

import json
import sys
from pathlib import Path

OPERATIONS = {payload_text}


def run(apply_changes: bool) -> dict:
    items = []
    renamed_count = 0
    reserved = set()
    for item in OPERATIONS:
        source = Path(item["source_path"])
        target_raw = item.get("target_path")
        status = item["status"]
        if not target_raw or status not in {{"ready", "unchanged"}}:
            items.append(item)
            continue

        target = Path(target_raw)
        if status == "unchanged" or not apply_changes:
            preview_item = dict(item)
            if not apply_changes and status == "ready":
                preview_item["status"] = "preview"
            items.append(preview_item)
            continue

        counter = 1
        while (target.exists() and target != source) or target in reserved:
            target = target.with_name(f"{{target.stem}}_{{counter}}{{target.suffix}}")
            counter += 1

        source.rename(target)
        reserved.add(target)
        renamed_count += 1
        applied_item = dict(item)
        applied_item["target_path"] = str(target)
        applied_item["status"] = "renamed"
        items.append(applied_item)

    return {{
        "renamed_count": renamed_count,
        "items": items,
        "applied": apply_changes,
    }}


if __name__ == "__main__":
    result = run("--apply" in sys.argv)
    print(json.dumps(result, ensure_ascii=False, indent=2))
"""
