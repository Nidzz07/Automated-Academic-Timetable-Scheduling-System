import React from 'react';
import { UserRole, ROLE_CAPABILITIES } from '@/types/roles';
import { Badge } from '@/components/ui/badge';
import { Shield, UserCheck, GraduationCap, School, Lock, Move } from 'lucide-react';

interface RoleSelectorProps {
  currentRole: UserRole;
  onRoleChange: (role: UserRole) => void;
  selectedFaculty: string;
  onFacultyChange: (faculty: string) => void;
  selectedStudentDivision: string;
  onStudentDivisionChange: (division: string) => void;
}

const ROLE_ICONS: Record<UserRole, React.ComponentType<{ className?: string }>> = {
  administrator: Shield,
  coordinator: UserCheck,
  faculty: School,
  student: GraduationCap,
};

export const RoleSelector: React.FC<RoleSelectorProps> = ({
  currentRole,
  onRoleChange,
  selectedFaculty,
  onFacultyChange,
  selectedStudentDivision,
  onStudentDivisionChange,
}) => {
  const caps = ROLE_CAPABILITIES[currentRole];

  return (
    <div
      data-testid="role-selector"
      className="rounded-2xl border border-border/70 bg-card/70 p-3.5 shadow-sm backdrop-blur-md space-y-3"
    >
      {/* Top: Role Tabs */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-1.5 p-1 rounded-xl bg-muted/60 border border-border/50">
          {(Object.keys(ROLE_CAPABILITIES) as UserRole[]).map((role) => {
            const Icon = ROLE_ICONS[role];
            const isSelected = currentRole === role;
            const roleCaps = ROLE_CAPABILITIES[role];

            return (
              <button
                key={role}
                data-testid={`role-button-${role}`}
                onClick={() => onRoleChange(role)}
                className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${
                  isSelected
                    ? 'bg-background text-foreground shadow-sm border border-border/80'
                    : 'text-muted-foreground hover:text-foreground hover:bg-background/50'
                }`}
              >
                <Icon className={`h-3.5 w-3.5 ${isSelected ? 'text-primary' : 'text-muted-foreground'}`} />
                <span>{roleCaps.title}</span>
                {roleCaps.canDragAndDrop ? (
                  <span className="hidden md:inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" title="Drag & Drop Enabled" />
                ) : (
                  <span className="hidden md:inline-flex h-1.5 w-1.5 rounded-full bg-slate-400" title="Read-Only" />
                )}
              </button>
            );
          })}
        </div>

        {/* Capability Pill */}
        <div className="flex items-center gap-2">
          {caps.canDragAndDrop ? (
            <Badge
              variant="success"
              data-testid="capability-badge-drag"
              className="text-[11px] gap-1 py-1 font-medium bg-emerald-500/15 text-emerald-800 dark:text-emerald-300 border-emerald-500/30"
            >
              <Move className="h-3 w-3" />
              <span>Drag-and-Drop Enabled</span>
            </Badge>
          ) : (
            <Badge
              variant="outline"
              data-testid="capability-badge-readonly"
              className="text-[11px] gap-1 py-1 font-medium text-muted-foreground border-border bg-muted/40"
            >
              <Lock className="h-3 w-3 text-slate-500" />
              <span>Read-Only View</span>
            </Badge>
          )}

          <Badge variant="outline" className="text-[10px] font-mono capitalize">
            Scope: {caps.viewScope.replace('-', ' ')}
          </Badge>
        </div>
      </div>

      {/* Role Context Bar & Persona Sub-Selectors */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pt-2 border-t border-border/50 text-xs">
        <p className="text-muted-foreground font-medium text-[11px]">
          {caps.description}
        </p>

        {/* Faculty Sub-Selector */}
        {currentRole === 'faculty' && (
          <div
            data-testid="faculty-persona-selector"
            className="flex items-center gap-2 shrink-0 bg-muted/40 px-2.5 py-1 rounded-lg border border-border/60"
          >
            <span className="font-semibold text-foreground">Teacher:</span>
            <select
              aria-label="Select faculty persona"
              value={selectedFaculty}
              onChange={(e) => onFacultyChange(e.target.value)}
              className="bg-transparent font-medium text-foreground outline-hidden cursor-pointer"
            >
              <option value="AGN">Prof. AGN (Dr. Abha N. — OS)</option>
              <option value="NR">Prof. NR (DAA / Algorithms)</option>
              <option value="JS">Prof. JS (CCN / Networks)</option>
              <option value="DN">Prof. DN (PCS / Systems)</option>
              <option value="KKD">Prof. KKD (Operating Systems)</option>
            </select>
          </div>
        )}

        {/* Student Sub-Selector */}
        {currentRole === 'student' && (
          <div
            data-testid="student-division-selector"
            className="flex items-center gap-2 shrink-0 bg-muted/40 px-2.5 py-1 rounded-lg border border-border/60"
          >
            <span className="font-semibold text-foreground">Enrolled Division:</span>
            <select
              aria-label="Select student division"
              value={selectedStudentDivision}
              onChange={(e) => onStudentDivisionChange(e.target.value)}
              className="bg-transparent font-medium text-foreground outline-hidden cursor-pointer"
            >
              <option value="coh-div-se-b">SE-Comp Division B</option>
              <option value="coh-div-se-c">SE-Comp Division C</option>
            </select>
          </div>
        )}
      </div>
    </div>
  );
};
