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
    title: 'Administrator',
    description: 'Full scheduling privileges across all divisions. Drag-and-drop enabled, quality scores and solver simulation active.',
  },
  coordinator: {
    canDragAndDrop: true,
    viewScope: 'all',
    showQualityScore: true,
    showSolverTelemetry: true,
    showSimulationControls: true,
    title: 'Timetable Coordinator',
    description: 'Department-wide timetable management and conflict resolution. Drag-and-drop enabled with validation.',
  },
  faculty: {
    canDragAndDrop: false,
    viewScope: 'own-faculty',
    showQualityScore: false,
    showSolverTelemetry: false,
    showSimulationControls: false,
    title: 'Faculty Member',
    description: 'Personal teaching timetable with theory/practical workload metrics. Read-only view.',
  },
  student: {
    canDragAndDrop: false,
    viewScope: 'own-student',
    showQualityScore: false,
    showSolverTelemetry: false,
    showSimulationControls: false,
    title: 'Student',
    description: 'Division and batch schedule. Clean read-only view with no internal solver metrics.',
  },
};
