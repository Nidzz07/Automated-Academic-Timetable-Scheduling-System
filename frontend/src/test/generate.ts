import { fireEvent, screen } from '@testing-library/react';

/** Press Generate and answer its confirm step with Generate. */
export const clickGenerate = () => {
  fireEvent.click(screen.getByTestId('solve-button'));
  fireEvent.click(screen.getByTestId('confirm-generate-button'));
};
