import React from 'react';

/**
 * What makes a session card reachable by keyboard: it is a focusable button whose Enter opens the
 * details. A draggable card keeps dnd-kit's attributes and listeners, and its Space picks it up
 * (TimetableGrid sets the keyboard sensor's start key to Space only); Enter while it is being
 * dragged drops it, so it opens nothing then.
 */
export function cardProps(
  onSelect: (() => void) | undefined,
  isDraggable: boolean,
  isDragging: boolean,
  dragAttributes?: Record<string, unknown>,
  dragListeners?: Record<string, unknown>
): React.HTMLAttributes<HTMLElement> {
  const drag = isDraggable ? { ...dragAttributes, ...dragListeners } : {};
  if (!onSelect) return drag;
  const dragKeyDown = (isDraggable ? dragListeners?.onKeyDown : undefined) as React.KeyboardEventHandler<HTMLElement> | undefined;
  return {
    ...drag,
    role: 'button',
    tabIndex: 0,
    onClick: onSelect,
    onKeyDown: (event) => {
      if (event.key === 'Enter' || (event.key === ' ' && !isDraggable)) {
        event.preventDefault();
        if (!isDragging) onSelect();
        return;
      }
      dragKeyDown?.(event);
    },
  };
}

/** Shown when a card has the keyboard focus. */
export const CARD_FOCUS = 'outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1';
