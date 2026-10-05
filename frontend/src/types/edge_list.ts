/**
 * TypeScript definitions mirroring contracts/edge_list_v1.schema.json.
 * 
 * Frozen Contract 2 of 3: DB -> Solver (edge-list contract).
 * Used here for type-safe session and problem instance metadata lookup in the frontend.
 */

import { DayIndex, PeriodIndex, Id } from './solution';

export type SessionType = "theory" | "lab";

export interface FixedSlot {
  day: DayIndex;
  period: PeriodIndex;
}

export interface EdgeListSession {
  id: Id;
  subject_id: Id;
  faculty_id: Id;
  cohort_id: Id;
  session_type: SessionType;
  duration_periods: number;
  cohort_size: number;
  requires_lab: boolean;
  fixed_slot: FixedSlot | null;
}

export interface EdgeListRoom {
  id: Id;
  code: string;
  capacity: number;
  is_lab: boolean;
  parent_room_id: Id | null;
}

export interface LabBlockDefinition {
  id: Id;
  session_ids: Id[];
  duration_periods: number;
  must_be_contiguous: boolean;
}

export interface PinnedOccupancy {
  day: DayIndex;
  period: PeriodIndex;
  faculty_ids: Id[];
  room_ids: Id[];
  cohort_ids: Id[];
}

export interface SlotGridDefinition {
  days: number;
  periods_per_day: number;
  teaching_periods: PeriodIndex[];
  adjacency: [PeriodIndex, PeriodIndex][];
}

export interface EdgeListContract {
  schema_version: "edge_list.v1";
  slot_grid: SlotGridDefinition;
  sessions: EdgeListSession[];
  edges: Array<{ u: Id; v: Id; reason: "FACULTY" | "ROOM" | "COHORT" }>;
  rooms: EdgeListRoom[];
  faculty_availability: Array<{
    faculty_id: Id;
    unavailable_slots: Array<{ day: DayIndex; period: PeriodIndex }>;
  }>;
  lab_blocks: LabBlockDefinition[];
  pinned_occupancy: PinnedOccupancy[];
}
