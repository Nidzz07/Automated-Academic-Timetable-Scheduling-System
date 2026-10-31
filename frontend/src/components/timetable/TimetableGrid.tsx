import React, { useMemo, useRef, useState } from 'react';
import {
  CollisionDetection,
  DndContext,
  DragEndEvent,
  DragStartEvent,
  DragOverlay,
  KeyboardCode,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
  useDraggable,
  useDroppable,
  pointerWithin,
  rectIntersection,
} from '@dnd-kit/core';
import { SolvedSolution, DayIndex } from '@/adapters/solution';
import {
  DAY_NAMES,
  EdgeList,
  buildWeekGrid,
  getExampleEdgeList,
  getSolvedSolutionFixture,
  buildEnrichedSessions,
  buildEnrichedLabBlocks,
  buildPins,
  EnrichedPin,
  EnrichedSession,
  EXAMPLE_LABELS,
  Labels,
  slotText,
} from '@/adapters/timetable';
import { periodLabel } from '@/lib/format';
import { DRAG_INSTRUCTIONS, dragAnnouncements, pinKindLabel } from '@/lib/wording';
import { ParallelLabBlock } from './ParallelLabBlock';
import { CombinedLectureBlock } from './CombinedLectureBlock';
import { PinnedBlock } from './PinnedBlock';
import { SessionCell } from './SessionCell';
import { Coffee, Utensils } from 'lucide-react';

type MoveHandler = (sessionId: string, targetDay: DayIndex, targetPeriod: number) => void;

/**
 * A drop lands in the cell under the pointer, not the one under the dragged card's centre (near the
 * top of the grid the card hangs below the pointer). Where the pointer is outside every cell, the
 * cell the card overlaps most, as dnd-kit's default (rectIntersection) picks.
 */
export const pointerCellFirst: CollisionDetection = (args) => {
  const underPointer = pointerWithin(args);
  return underPointer.length > 0 ? underPointer : rectIntersection(args);
};

export interface TimetableGridProps {
  /**
   * The edge list the solution was solved for: days, periods, breaks, rooms, pinned occupancy.
   * Defaults to contracts/examples/edge_list_v1.example.json.
   */
  edgeList?: EdgeList;
  /**
   * The placements to show (a solved solution, or the printed baseline); null shows the grid
   * with no sessions. Defaults to contracts/examples/solution_v2.solved.example.json.
   */
  solution?: Pick<SolvedSolution, 'assignment'> | null;
  /** Sessions outlined as in violation (the printed baseline's violations) */
  flaggedSessionIds?: ReadonlySet<string>;
  /** 'change': the flagged sessions are a proposed repair's changes, outlined in amber */
  flagTone?: 'violation' | 'change';
  /** Names, pin kinds and clock times for the edge list's ids; defaults to the contract examples' */
  labels?: Labels;
  /** Cohort filter: 'all' or a cohort id; overlapping cohorts (batches of a division) are shown */
  cohortFilter?: string;
  /** Optional click handler when a session card is selected */
  onSelectSession?: (sessionId: string) => void;
  /** Whether to render immovable institutional pinned blocks */
  showPinnedBlocks?: boolean;
  /** A teacher's own view: only the pinned blocks that name them, which their weekly load counts */
  pinsOfFaculty?: string;
  /** Whether drag-and-drop is enabled for the current user role */
  canDragAndDrop?: boolean;
  /** Currently selected session ID (for persistent selection highlight) */
  selectedSessionId?: string | null;
  /** Session ID currently being optimistically validated */
  provisionalSessionId?: string | null;
  /** Handler invoked when a session is dropped onto a slot (wall-clock period) */
  onMoveSession?: MoveHandler;
}

/**
 * Droppable Cell Component for a Grid Slot
 */
interface DroppableGridCellProps {
  day: DayIndex;
  period: number;
  rowSpan?: number;
  spansAdjacent?: boolean;
  canDragAndDrop?: boolean;
  className?: string;
  activeDragSessionId?: string | null;
  onMoveSession?: MoveHandler;
  /** The drop target that has the keyboard focus during a drag: a keyboard drop lands there */
  onDropTargetFocus?: (slot: { day: DayIndex; period: number } | null) => void;
  children: React.ReactNode;
}

const DroppableGridCell: React.FC<DroppableGridCellProps> = ({
  day,
  period,
  rowSpan = 1,
  spansAdjacent = false,
  canDragAndDrop = true,
  className = '',
  activeDragSessionId,
  onMoveSession,
  onDropTargetFocus,
  children,
}) => {
  const slotId = `slot-${day}-${period}`;
  const { setNodeRef, isOver } = useDroppable({
    id: slotId,
    disabled: !canDragAndDrop,
    data: { day, period },
  });

  return (
    <td
      ref={setNodeRef}
      data-testid={`grid-cell-${day}-${period}`}
      data-slot-id={slotId}
      data-is-over={isOver ? 'true' : 'false'}
      rowSpan={rowSpan}
      data-rowspan={rowSpan}
      data-spans-adjacent={spansAdjacent ? 'true' : 'false'}
      onDrop={(e) => {
        if (!canDragAndDrop) return;
        const sessionId = e.dataTransfer?.getData('text/plain') || activeDragSessionId;
        if (sessionId && onMoveSession) {
          onMoveSession(sessionId, day, period);
        }
      }}
      onDragOver={(e) => {
        if (canDragAndDrop) e.preventDefault();
      }}
      className={`p-2 align-top border-r last:border-r-0 border-border min-h-[90px] relative ${
        isOver && canDragAndDrop ? 'bg-primary/15 ring-2 ring-primary ring-inset' : ''
      } ${className}`}
    >
      {/* Only during a drag: otherwise these 45 buttons would come before the content in the tab order */}
      {canDragAndDrop && activeDragSessionId && (
        <button
          type="button"
          data-testid={`drop-slot-${day}-${period}`}
          // invisible until the keyboard reaches it; it never takes a pointer drag's events
          className="pointer-events-none absolute inset-1 z-20 flex items-start justify-center rounded-md bg-primary/10 p-2 opacity-0 outline-none ring-4 ring-primary focus:opacity-100"
          onFocus={() => onDropTargetFocus?.({ day, period })}
          onBlur={() => onDropTargetFocus?.(null)}
          onClick={() => onMoveSession?.(activeDragSessionId, day, period)}
        >
          <span className="rounded bg-primary px-2 py-1 font-semibold text-primary-foreground">Drop into {slotText(day, period)}</span>
        </button>
      )}
      {children}
    </td>
  );
};

/**
 * Draggable Session Wrapper
 */
interface DraggableSessionItemProps {
  session: EnrichedSession;
  canDragAndDrop?: boolean;
  isProvisional?: boolean;
  isSelected?: boolean;
  onSelect?: () => void;
}

const DraggableSessionItem: React.FC<DraggableSessionItemProps> = ({
  session,
  canDragAndDrop = false,
  isProvisional = false,
  isSelected = false,
  onSelect,
}) => {
  const isDraggable = canDragAndDrop && !session.isPinned;
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: session.sessionId,
    disabled: !isDraggable,
    data: { session },
  });

  if (session.isCombinedDivision) {
    return (
      <CombinedLectureBlock
        session={session}
        onSelect={onSelect}
        isDraggable={isDraggable}
        isProvisional={isProvisional}
        isSelected={isSelected}
        dragRef={setNodeRef}
        dragAttributes={attributes}
        dragListeners={listeners}
        isDragging={isDragging}
      />
    );
  }

  return (
    <SessionCell
      session={session}
      onSelect={onSelect}
      isDraggable={isDraggable}
      isProvisional={isProvisional}
      isSelected={isSelected}
      dragRef={setNodeRef}
      dragAttributes={attributes}
      dragListeners={listeners}
      isDragging={isDragging}
    />
  );
};

export const TimetableGrid: React.FC<TimetableGridProps> = ({
  edgeList = getExampleEdgeList(),
  solution = getSolvedSolutionFixture(),
  labels = EXAMPLE_LABELS,
  cohortFilter = 'all',
  onSelectSession,
  showPinnedBlocks = true,
  pinsOfFaculty,
  canDragAndDrop = true,
  selectedSessionId = null,
  provisionalSessionId = null,
  onMoveSession,
  flaggedSessionIds,
  flagTone = 'violation',
}) => {
  const flagClass = flagTone === 'change' ? 'ring-2 ring-amber-500' : 'ring-2 ring-destructive';
  const [activeDragSessionId, setActiveDragSessionId] = useState<string | null>(null);
  // During a keyboard drag, the cell whose drop target has the focus (Tab moves it)
  const focusedDropTarget = useRef<{ day: DayIndex; period: number } | null>(null);

  // Configure dnd-kit sensors. Space picks a session up and Enter opens its details (cardKeyboard.ts);
  // Tab does not end a drag, so it can reach the drop targets
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 4,
      },
    }),
    useSensor(KeyboardSensor, {
      keyboardCodes: {
        start: [KeyboardCode.Space],
        cancel: [KeyboardCode.Esc],
        end: [KeyboardCode.Space, KeyboardCode.Enter],
      },
    })
  );

  // 1. Days, periods and breaks from the edge list's slot_grid
  const grid = useMemo(() => buildWeekGrid(edgeList), [edgeList]);

  // 2. Build enriched sessions from the solution's placements
  const sessions = useMemo(
    () => buildEnrichedSessions(solution?.assignment ?? [], edgeList, labels),
    [solution, edgeList, labels]
  );

  const filteredSessions = useMemo(
    () =>
      cohortFilter === 'all'
        ? sessions
        : sessions.filter((s) => labels.overlap(s.cohortId, cohortFilter)),
    [sessions, cohortFilter, labels]
  );

  // 3. Parallel lab blocks of the sessions in view
  const filteredLabBlocks = useMemo(() => buildEnrichedLabBlocks(filteredSessions), [filteredSessions]);

  // 4. Pinned occupancy (frozen items and each year's lunch) holding a cohort in view
  const filteredPins = useMemo(() => {
    if (!showPinnedBlocks) return [];
    const pins = buildPins(edgeList, labels);
    if (pinsOfFaculty) return pins.filter((p) => p.facultyIds.includes(pinsOfFaculty));
    if (cohortFilter === 'all') return pins;
    return pins.filter((p) => p.cohortIds.some((c) => labels.overlap(c, cohortFilter)));
  }, [edgeList, cohortFilter, showPinnedBlocks, pinsOfFaculty, labels]);
  // A card names the cohorts in view: one pin can hold dozens, and a filter asks about one division
  const pinCohortsInView = (pin: EnrichedPin) =>
    cohortFilter === 'all'
      ? pin.cohortLabels
      : pin.cohortIds.filter((c) => labels.overlap(c, cohortFilter)).map((c) => labels.cohort(c));

  // Cells under a multi-period lab block (break rows included) are covered by its rowSpan
  const coveredSlots = useMemo(() => {
    const set = new Set<string>();
    filteredLabBlocks.forEach((lb) => {
      for (let p = lb.periods[0] + 1; p <= lb.periods[lb.periods.length - 1]; p++) {
        set.add(`${lb.day}-${p}`);
      }
    });
    return set;
  }, [filteredLabBlocks]);

  // Drag handlers
  const handleDragStart = (event: DragStartEvent) => {
    setActiveDragSessionId(String(event.active.id));
  };

  const handleDragCancel = () => {
    focusedDropTarget.current = null;
    setActiveDragSessionId(null);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    const focused = focusedDropTarget.current;
    focusedDropTarget.current = null;
    setActiveDragSessionId(null);
    if (focused && active) {
      onMoveSession?.(String(active.id), focused.day, focused.period);
      return;
    }
    if (!over || !active) return;

    const sessionId = String(active.id);
    const overId = String(over.id);
    const match = overId.match(/^slot-(\d+)-(\d+)$/);
    if (!match) return;

    if (onMoveSession) {
      onMoveSession(sessionId, Number(match[1]) as DayIndex, Number(match[2]));
    }
  };

  const activeDragSession = useMemo(() => {
    if (!activeDragSessionId) return null;
    return sessions.find((s) => s.sessionId === activeDragSessionId) ?? null;
  }, [activeDragSessionId, sessions]);

  // During a drag Tab goes from cell to cell: everything but the dragged card is out of the tab order
  const outOfTabOrder = activeDragSessionId ? { inert: '' } : {};

  // dnd-kit's live region would read out session ids and "droppable slot-1-3"
  const sessionWords = (id: string | number) => {
    const s = sessions.find((x) => x.sessionId === String(id));
    return s ? `${s.subjectCode} · ${s.cohortLabel}` : 'The session';
  };
  const cellWords = (id: string | number) => {
    const m = String(id).match(/^slot-(\d+)-(\d+)$/);
    return m ? slotText(Number(m[1]), Number(m[2])) : '';
  };

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={pointerCellFirst}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onDragCancel={handleDragCancel}
      accessibility={{
        screenReaderInstructions: { draggable: DRAG_INSTRUCTIONS },
        announcements: {
          onDragStart: ({ active }) => dragAnnouncements.picked(sessionWords(active.id)),
          onDragOver: ({ active, over }) =>
            over ? dragAnnouncements.over(sessionWords(active.id), cellWords(over.id)) : dragAnnouncements.outside(sessionWords(active.id)),
          onDragEnd: ({ active, over }) =>
            over ? dragAnnouncements.dropped(sessionWords(active.id), cellWords(over.id)) : dragAnnouncements.outside(sessionWords(active.id)),
          onDragCancel: ({ active }) => dragAnnouncements.cancelled(sessionWords(active.id)),
        },
      }}
    >
      {/*
        The five days share the width (fixed layout, wrapping text). Below 1100 px the box scrolls by
        itself, so its scrollbar stays on screen and its sticky headers and period column stick to it;
        wider, the page scrolls and the day headers stick to the window.
      */}
      <div
        data-testid="timetable-grid"
        className="w-full max-h-[85vh] overflow-auto rounded-lg border border-border bg-card min-[1100px]:max-h-none min-[1100px]:overflow-visible"
      >
        <table className="w-full min-w-[1000px] table-fixed border-collapse break-words text-left text-xs">
          {/* Table Header: Days of the week */}
          <thead>
            <tr className="border-b-2 border-border bg-muted">
              <th className="sticky left-0 top-0 z-30 w-24 bg-muted p-2 text-center font-sans text-sm font-semibold border-r border-border shadow-[inset_0_-2px_0_hsl(var(--border))]">
                Period
              </th>
              {grid.days.map((day) => (
                <th
                  key={day}
                  data-testid={`day-header-${day}`}
                  className="sticky top-0 z-20 bg-muted p-3 text-center font-serif text-lg font-semibold border-r last:border-r-0 border-border shadow-[inset_0_-2px_0_hsl(var(--border))]"
                >
                  {DAY_NAMES[day]}
                </th>
              ))}
            </tr>
          </thead>

          {/* Table Body: every wall-clock period of the edge list's slot_grid */}
          <tbody className="divide-y divide-border">
            {grid.periods.map(({ period, teaching }) =>
              !teaching ? (
                // Not a teaching period for anyone: a break row (lab blocks may straddle it)
                <tr
                  key={period}
                  data-testid={`break-row-${period}`}
                  className="bg-muted border-y border-dashed border-border"
                >
                  <td className="sticky left-0 z-10 bg-muted p-2 text-center font-semibold border-r border-border">
                    <span className="inline-flex items-center gap-1">
                      <Coffee aria-hidden="true" className="h-4 w-4" />
                      {periodLabel(period)}
                    </span>
                    {labels.clock(period) && <div className="font-normal">{labels.clock(period)}</div>}
                  </td>
                  {grid.days.map((day) =>
                    coveredSlots.has(`${day}-${period}`) ? null : (
                      <td
                        key={day}
                        className="p-1.5 text-center font-semibold"
                      >
                        Break
                      </td>
                    )
                  )}
                </tr>
              ) : (
                <tr
                  key={period}
                  data-testid={`period-row-${period}`}
                  className=""
                >
                  {/* Period Column */}
                  <td data-testid={`period-cell-${period}`} className="sticky left-0 z-10 p-2 text-center border-r border-border bg-muted align-top">
                    <div className="font-serif text-lg font-semibold">{periodLabel(period)}</div>
                    {labels.clock(period) && (
                      <div data-testid={`period-clock-${period}`} className="text-xs">
                        {labels.clock(period)}
                      </div>
                    )}
                  </td>

                  {/* Day Cells */}
                  {grid.days.map((day) => {
                    const slotKey = `${day}-${period}`;

                    // If this slot is covered by a multi-period spanning lab block, skip rendering cell
                    if (coveredSlots.has(slotKey)) {
                      return null;
                    }

                    // A parallel lab block starting in this slot
                    const labBlock = filteredLabBlocks.find(
                      (lb) => lb.day === day && lb.periods[0] === period
                    );
                    const lastPeriod = labBlock ? labBlock.periods[labBlock.periods.length - 1] : period;

                    // Sessions starting in this slot (lab-block members render inside their block)
                    const cellSessions = filteredSessions.filter(
                      (s) => s.day === day && s.wallClockPeriod === period && !s.labBlockId
                    );

                    // Pinned occupancy and lunch in this slot
                    const cellPins = filteredPins.filter((p) => p.day === day && p.period === period);

                    return (
                      <DroppableGridCell
                        key={slotKey}
                        day={day}
                        period={period}
                        rowSpan={lastPeriod - period + 1}
                        spansAdjacent={!!labBlock}
                        canDragAndDrop={canDragAndDrop}
                        activeDragSessionId={activeDragSessionId}
                        onMoveSession={onMoveSession}
                        onDropTargetFocus={(slot) => {
                          focusedDropTarget.current = slot;
                        }}
                        className=""
                      >
                        {/* 1. Multi-period Parallel Lab Block Case */}
                        {labBlock && (
                          <div className="contents" {...outOfTabOrder}>
                            <ParallelLabBlock
                              labBlock={labBlock}
                              onSelectSession={onSelectSession}
                              flaggedSessionIds={flaggedSessionIds}
                              flagClass={flagClass}
                            />
                          </div>
                        )}

                        {/* 2 & 3. Draggable Session (Combined Lecture or Standard Theory) */}
                        {cellSessions.map((session) => {
                          const flagged = !!flaggedSessionIds?.has(session.sessionId);
                          return (
                            <div
                              key={session.sessionId}
                              data-flagged={flagged || undefined}
                              className={flagged ? `rounded-xl ${flagClass}` : undefined}
                              {...(session.sessionId === activeDragSessionId ? {} : outOfTabOrder)}
                            >
                              <DraggableSessionItem
                                session={session}
                                canDragAndDrop={canDragAndDrop}
                                isProvisional={session.sessionId === provisionalSessionId}
                                isSelected={session.sessionId === selectedSessionId}
                                onSelect={() => onSelectSession?.(session.sessionId)}
                              />
                            </div>
                          );
                        })}

                        {/* 4. Pinned occupancy, labelled by its display kind (D41): lunch, a frozen item, an exam, ... */}
                        <div className="contents" {...outOfTabOrder}>
                        {cellPins.map((pin) =>
                          pin.kind === 'lunch' ? (
                            <div
                              key={pin.key}
                              data-testid={`lunch-cell-${day}-${period}`}
                              className="flex items-center justify-center gap-1.5 rounded-md border border-dashed border-orange-700/50 bg-orange-50 p-2 font-semibold text-orange-950 dark:bg-orange-950/40 dark:text-orange-200"
                            >
                              <Utensils aria-hidden="true" className="h-4 w-4" />
                              <span>{pin.label}</span>
                            </div>
                          ) : (
                            <PinnedBlock
                              key={pin.key}
                              id={pin.key}
                              label={pin.label ?? 'Fixed item'}
                              kind={pinKindLabel(pin.kind, pin.decision)}
                              teachers={pin.facultyNames.join(', ') || undefined}
                              roomCode={pin.roomCodes.join(', ') || undefined}
                              cohorts={pinCohortsInView(pin)}
                              listAll={cohortFilter !== 'all'}
                            />
                          )
                        )}
                        </div>

                        {/* Empty / Unscheduled Slot */}
                        {!labBlock && cellSessions.length === 0 && cellPins.length === 0 && (
                          <div className="flex h-16 w-full items-center justify-center rounded-md border border-dashed border-border select-none">
                            {canDragAndDrop ? 'Free: drop a session here' : 'Free'}
                          </div>
                        )}
                      </DroppableGridCell>
                    );
                  })}
                </tr>
              )
            )}
          </tbody>
        </table>
      </div>

      {/* Drag Overlay preview */}
      <DragOverlay>
        {activeDragSession ? (
          <div className="w-64 opacity-90 scale-105 pointer-events-none">
            {activeDragSession.isCombinedDivision ? (
              <CombinedLectureBlock session={activeDragSession} isDraggable />
            ) : (
              <SessionCell session={activeDragSession} isDraggable />
            )}
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
};
