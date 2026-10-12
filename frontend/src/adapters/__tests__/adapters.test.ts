import { describe, it, expect } from 'vitest';
import { ContractValidationError } from '@/api/contractValidation';
import { isInfeasibleSolution, isSolvedSolution, parseSolution } from '../solution';
import {
  buildEnrichedLabBlocks,
  buildEnrichedSessions,
  getSolvedSolutionFixture,
} from '../timetable';
import solvedExample from '@contracts/examples/solution_v1.solved.example.json';
import infeasibleExample from '@contracts/examples/solution_v1.infeasible.example.json';

describe('solution adapter', () => {
  it('narrows validated payloads to the solved / infeasible view types', () => {
    const solved = parseSolution(solvedExample);
    const infeasible = parseSolution(infeasibleExample);
    expect(isSolvedSolution(solved)).toBe(true);
    expect(isInfeasibleSolution(infeasible)).toBe(true);
  });

  it('refuses a payload that is not a solution_v1 contract', () => {
    expect(() => parseSolution({ status: 'solved' })).toThrow(ContractValidationError);
  });
});

describe('timetable adapter', () => {
  const sessions = buildEnrichedSessions(getSolvedSolutionFixture());

  it('maps an assignment plus edge-list and ingestion metadata to a session view model', () => {
    const os = sessions.find((s) => s.sessionId === 'sess-0006');
    expect(os).toMatchObject({
      day: 2,
      wallClockPeriod: 3,
      teachingPeriod: 2, // wall-clock 3 is the third teaching period (short break at 2)
      durationPeriods: 1,
      roomCode: '002',
      subRoomCode: null,
      subjectCode: 'OS',
      subjectName: 'Operating Systems',
      cohortLabel: 'SE-Comp C',
      cohortSize: 70,
      sessionType: 'theory',
      isPinned: false,
    });
  });

  it('groups lab-block members into one parallel lab block', () => {
    const blocks = buildEnrichedLabBlocks(sessions);
    expect(blocks).toHaveLength(1);
    expect(blocks[0].blockId).toBe('labblk-0001');
    expect(blocks[0].sessions.map((s) => s.sessionId).sort()).toEqual([
      'sess-0001',
      'sess-0002',
      'sess-0003',
      'sess-0004',
    ]);
  });
});
