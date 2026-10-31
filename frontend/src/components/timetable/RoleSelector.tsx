import React from 'react';
import { UserRole, ROLE_CAPABILITIES } from '@/types/roles';
import { UI } from '@/lib/wording';

interface RoleSelectorProps {
  currentRole: UserRole;
  /** Static/demo mode only; without it (http mode) the role is the login's and only shown */
  onRoleChange?: (role: UserRole) => void;
  selectedFaculty: string;
  onFacultyChange: (faculty: string) => void;
  selectedStudentDivision: string;
  onStudentDivisionChange: (division: string) => void;
  /** Faculty placed in the timetable (from the payload): id and "Name (INITIALS)" */
  facultyOptions: Array<{ id: string; label: string }>;
  /** Cohorts named in the edge list */
  cohortOptions: Array<{ id: string; label: string }>;
  /** The account is linked to this teacher or cohort (D50): its picker is locked */
  personaLocked?: boolean;
}

const pickerClass = 'flex shrink-0 items-center gap-2 rounded-md border border-input bg-card px-2.5 py-1.5';

export const RoleSelector: React.FC<RoleSelectorProps> = ({
  currentRole,
  onRoleChange,
  selectedFaculty,
  onFacultyChange,
  selectedStudentDivision,
  onStudentDivisionChange,
  facultyOptions,
  cohortOptions,
  personaLocked = false,
}) => {
  const caps = ROLE_CAPABILITIES[currentRole];

  return (
    <div data-testid="role-selector" className="space-y-3 rounded-lg border border-border bg-card p-4">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
        {!onRoleChange ? (
          <p data-testid="session-role" className="font-serif text-lg font-semibold">
            {caps.title}
          </p>
        ) : (
          <div role="group" aria-label="View as" className="flex flex-wrap items-center gap-1">
            {(Object.keys(ROLE_CAPABILITIES) as UserRole[]).map((role) => (
              <button
                key={role}
                data-testid={`role-button-${role}`}
                onClick={() => onRoleChange(role)}
                aria-pressed={currentRole === role}
                className={`rounded-md border px-3 py-1.5 font-semibold ${
                  currentRole === role ? 'border-primary bg-primary text-primary-foreground' : 'border-input bg-card hover:bg-muted'
                }`}
              >
                {ROLE_CAPABILITIES[role].title}
              </button>
            ))}
          </div>
        )}

        <p className="text-xs">
          {caps.canDragAndDrop ? (
            <span data-testid="capability-badge-drag" className="font-semibold">
              {UI.canMoveSessions}
            </span>
          ) : (
            <span data-testid="capability-badge-readonly" className="font-semibold">
              {UI.readOnly}
            </span>
          )}
          {', '}
          {caps.viewScope === 'all' ? 'whole department' : caps.viewScope === 'own-faculty' ? 'own teaching only' : 'own class only'}
        </p>
      </div>

      <div className="flex flex-col justify-between gap-2 border-t border-border pt-3 sm:flex-row sm:items-center">
        <p>{caps.description}</p>

        {currentRole === 'faculty' && (
          <label data-testid="faculty-persona-selector" className={pickerClass}>
            <span className="font-semibold">Teacher:</span>
            <select
              aria-label="Select teacher"
              disabled={personaLocked}
              value={selectedFaculty}
              onChange={(e) => onFacultyChange(e.target.value)}
              className="cursor-pointer bg-transparent font-medium outline-none disabled:cursor-default"
            >
              {facultyOptions.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.label}
                </option>
              ))}
            </select>
          </label>
        )}

        {currentRole === 'student' && (
          <label data-testid="student-division-selector" className={pickerClass}>
            <span className="font-semibold">Class:</span>
            <select
              aria-label="Select class"
              disabled={personaLocked}
              value={selectedStudentDivision}
              onChange={(e) => onStudentDivisionChange(e.target.value)}
              className="cursor-pointer bg-transparent font-medium outline-none disabled:cursor-default"
            >
              {cohortOptions.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
    </div>
  );
};
