import '@testing-library/jest-dom';
import { configure } from '@testing-library/react';

// findBy/waitFor wait 1 s by default; the real instance's first render alone can take that with files in parallel
configure({ asyncUtilTimeout: 5000 });
