/**
 * TypeScript bindings for the GOAL metamodel v0.1.
 *
 * Hand-maintained to mirror schema/goal.schema.json. When the schema
 * changes, update these types in the same commit and bump the version
 * below. Breaking type changes bump the major version.
 *
 * @version 0.1.0 (mirrors schema/goal.schema.json)
 */

export type AgentType = "human" | "team" | "organization" | "system";
export type GoalPriority = "critical" | "high" | "medium" | "low";
export type GoalStatus = "proposed" | "active" | "achieved" | "abandoned";
export type Refinement = "and" | "or";
export type Verification = "manual" | "automated";
export type ConstraintKind = "budget" | "time" | "resource" | "policy" | "other";

export interface Agent {
  id: string;
  name: string;
  type: AgentType;
  contact?: string;
}

export interface State {
  id: string;
  description: string;
  /** Declared current situation of the world. Default: false. */
  isCurrent?: boolean;
}

export interface Criterion {
  description: string;
  /** Where or how to check this criterion. */
  evidence?: string;
  verification?: Verification;
}

export interface Constraint {
  id: string;
  description: string;
  kind: ConstraintKind;
}

export interface Obstacle {
  id: string;
  description: string;
  /** Goal id or goal ids threatened by this obstacle. */
  threatens: string | string[];
  /** Goal id that mitigates this obstacle. */
  mitigation?: string;
}

export interface Goal {
  id: string;
  /** Statement of the desired state of the world. */
  statement: string;
  /** Owning Agent id. Mandatory (design rule R5). */
  owner: string;
  /** Target State id. */
  targetState?: string;
  successCriteria?: Criterion[];
  /** Contributing Agent ids. */
  contributors?: string[];
  priority?: GoalPriority;
  status?: GoalStatus;
  /** ISO date (YYYY-MM-DD). */
  deadline?: string;
  /** Subgoal Goal ids. */
  subgoals?: string[];
  /** Required when subgoals is non-empty: 'and' = all, 'or' = at least one. */
  refinement?: Refinement;
  /** Goal ids that must be achieved first. */
  dependsOn?: string[];
  /** Constraint ids limiting how this goal may be pursued. */
  constraints?: string[];
  /** Required when status is 'abandoned'. */
  abandonReason?: string;
}

export interface GoalModel {
  id: string;
  name: string;
  /** Model version (semver). */
  version: string;
  description?: string;
  /** Metamodel version this instance conforms to. */
  schemaVersion?: string;
  agents: Agent[];
  states?: State[];
  goals: Goal[];
  obstacles?: Obstacle[];
  constraints?: Constraint[];
}
