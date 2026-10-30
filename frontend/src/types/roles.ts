/**
 * Role definitions and capability contracts.
 * 
 * ROADMAP.md Phase 2 Track C explicitly defines four roles:
 * - administrator
 * - coordinator
 * - faculty
 * - student
 * 
 * Roles differ by what each can SEE and DO:
 * - Read-only vs drag-enabled
 * - Whole-department vs own sessions
 * - Administrative telemetry vs student-friendly views
 */

export type UserRole = 'administrator' | 'coordinator' | 'faculty' | 'student';

export interface RoleCapabilities {
  /** Can drag-and-drop sessions on the timetable grid */
  canDragAndDrop: boolean;
  /** Scope of sessions visible by default */
  viewScope: 'all' | 'own-faculty' | 'own-student';
  /** Can see solver quality score and penalty breakdown */
  showQualityScore: boolean;
  /** Can see solver engine run statistics (algorithm, ms, backtracks) */
  showSolverTelemetry: boolean;
  /** Can access diagnosis and relaxation simulation toggles */
  showSimulationControls: boolean;
  /** Can run the solver on a backend instance (S13a: administrator and coordinator only) */
  canSolve: boolean;
  /** Label for display */
  title: string;
  /** Description of role permissions */
  description: string;
}

export const ROLE_CAPABILITIES: Record<UserRole, RoleCapabilities> = {
  administrator: {
    canDragAndDrop: true,
    viewScope: 'all',
    showQualityScore: true,
    showSolverTelemetry: true,
    showSimulationControls: true,
    canSolve: true,
    title: 'Administrator',
    description: 'Sees the whole department. Can move sessions, run the solver, repair the timetable and read the audit log.',
  },
  coordinator: {
    canDragAndDrop: true,
    viewScope: 'all',
    showQualityScore: true,
    showSolverTelemetry: true,
    showSimulationControls: true,
    canSolve: true,
    title: 'Timetable Coordinator',
    description: 'Manages the department timetable. Can move sessions, run the solver and repair the timetable.',
  },
  faculty: {
    canDragAndDrop: false,
    viewScope: 'own-faculty',
    showQualityScore: false,
    showSolverTelemetry: false,
    showSimulationControls: false,
    canSolve: false,
    title: 'Faculty Member',
    description: 'Your own teaching timetable and weekly load, in theory and practical hours. Read only.',
  },
  student: {
    canDragAndDrop: false,
    viewScope: 'own-student',
    showQualityScore: false,
    showSolverTelemetry: false,
    showSimulationControls: false,
    canSolve: false,
    title: 'Student',
    description: "Your division's and batch's timetable. Read only.",
  },
};
