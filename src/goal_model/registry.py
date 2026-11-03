"""Agent registry: administration of agents and their declared goal interfaces.

A user administers agents through this registry. Each registered agent
*declares an interface* (:class:`GoalInterface`) describing how it accepts
well-defined goals: which GOAL schema versions it understands, which goal
types it pursues, what capabilities it offers, and how many goals it can
hold active at once. The ingestion interface (``interface.py``) enforces
this declaration when a goal is offered to the agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .telemetry import EVENT_AGENT_REGISTERED, EVENT_AGENT_RETIRED, EventLog, utcnow_iso

INTERFACE_VERSION = "0.1.0"
AGENT_ACTIVE = "active"
AGENT_PAUSED = "paused"
AGENT_RETIRED = "retired"
AGENT_STATUSES = (AGENT_ACTIVE, AGENT_PAUSED, AGENT_RETIRED)
ANY_GOAL_TYPE = "*"


class RegistryError(Exception):
    """Raised on registry operations that cannot be performed."""


@dataclass
class GoalInterface:
    """The interface an agent declares for accepting well-defined goals.

    - ``version``: version of this interface contract itself.
    - ``schemaVersions``: GOAL metamodel versions the agent accepts.
    - ``goalTypes``: goal types the agent pursues (``"*"`` accepts any);
      used to home in typed assessors and typed admission.
    - ``capabilities``: e.g. ``accept-goals``, ``report-actions``,
      ``self-assess``.
    - ``maxActiveGoals``: capacity limit enforced at acceptance time.
    """

    version: str = INTERFACE_VERSION
    schema_versions: List[str] = field(default_factory=lambda: ["0.1.0"])
    goal_types: List[str] = field(default_factory=lambda: [ANY_GOAL_TYPE])
    capabilities: List[str] = field(default_factory=lambda: ["accept-goals"])
    max_active_goals: int = 10

    def accepts_schema_version(self, schema_version: str) -> bool:
        return schema_version in self.schema_versions

    def accepts_goal_type(self, goal_type: str) -> bool:
        return ANY_GOAL_TYPE in self.goal_types or goal_type in self.goal_types

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "schemaVersions": list(self.schema_versions),
            "goalTypes": list(self.goal_types),
            "capabilities": list(self.capabilities),
            "maxActiveGoals": self.max_active_goals,
        }

    @staticmethod
    def from_dict(raw: Dict[str, Any]) -> "GoalInterface":
        return GoalInterface(
            version=raw.get("version", INTERFACE_VERSION),
            schema_versions=list(raw.get("schemaVersions", ["0.1.0"])),
            goal_types=list(raw.get("goalTypes", [ANY_GOAL_TYPE])),
            capabilities=list(raw.get("capabilities", ["accept-goals"])),
            max_active_goals=int(raw.get("maxActiveGoals", 10)),
        )


@dataclass
class AgentRecord:
    id: str
    name: str
    type: str
    status: str = AGENT_ACTIVE
    interface: GoalInterface = field(default_factory=GoalInterface)
    registered_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.registered_at:
            self.registered_at = utcnow_iso()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "status": self.status,
            "interface": self.interface.to_dict(),
            "registeredAt": self.registered_at,
            "metadata": dict(self.metadata),
        }

    @staticmethod
    def from_dict(raw: Dict[str, Any]) -> "AgentRecord":
        return AgentRecord(
            id=raw["id"],
            name=raw["name"],
            type=raw["type"],
            status=raw.get("status", AGENT_ACTIVE),
            interface=GoalInterface.from_dict(raw.get("interface", {})),
            registered_at=raw.get("registeredAt", ""),
            metadata=dict(raw.get("metadata", {})),
        )


class AgentRegistry:
    """CRUD over registered agents, persisted in the operations store."""

    def __init__(self, store, events: Optional[EventLog] = None):
        self.store = store
        self.events = events

    def register(
        self,
        id: str,
        name: str,
        type: str,
        interface: Optional[GoalInterface] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentRecord:
        if any(a["id"] == id for a in self.store.load_agents()):
            raise RegistryError(f"agent id already registered: {id}")
        record = AgentRecord(
            id=id,
            name=name,
            type=type,
            interface=interface or GoalInterface(),
            metadata=metadata or {},
        )
        agents = self.store.load_agents()
        agents.append(record.to_dict())
        self.store.save_agents(agents)
        if self.events is not None:
            self.events.append(
                EVENT_AGENT_REGISTERED,
                agent_id=id,
                interface=record.interface.to_dict(),
            )
        return record

    def get(self, agent_id: str) -> AgentRecord:
        for raw in self.store.load_agents():
            if raw["id"] == agent_id:
                return AgentRecord.from_dict(raw)
        raise RegistryError(f"unknown agent: {agent_id}")

    def list(self, status: Optional[str] = None) -> List[AgentRecord]:
        records = [AgentRecord.from_dict(r) for r in self.store.load_agents()]
        if status is not None:
            records = [r for r in records if r.status == status]
        return records

    def update(
        self,
        agent_id: str,
        name: Optional[str] = None,
        status: Optional[str] = None,
        interface: Optional[GoalInterface] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentRecord:
        if status is not None and status not in AGENT_STATUSES:
            raise RegistryError(f"invalid agent status: {status}")
        agents = self.store.load_agents()
        for raw in agents:
            if raw["id"] == agent_id:
                if name is not None:
                    raw["name"] = name
                if status is not None:
                    raw["status"] = status
                if interface is not None:
                    raw["interface"] = interface.to_dict()
                if metadata is not None:
                    raw["metadata"] = metadata
                self.store.save_agents(agents)
                return AgentRecord.from_dict(raw)
        raise RegistryError(f"unknown agent: {agent_id}")

    def retire(self, agent_id: str) -> AgentRecord:
        record = self.update(agent_id, status=AGENT_RETIRED)
        if self.events is not None:
            self.events.append(EVENT_AGENT_RETIRED, agent_id=agent_id)
        return record
