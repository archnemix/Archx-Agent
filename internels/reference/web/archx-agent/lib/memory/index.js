'use strict';

const MEMORY_TYPES = Object.freeze([
  'permanent',
  'project',
  'learning',
  'procedural',
  'task',
  'knowledge',
]);

const MEMORY_LABELS = Object.freeze({
  permanent: 'Permanent memory',
  project: 'Project / workspace memory',
  learning: 'Learning memory',
  procedural: 'Procedural memory',
  task: 'Task / goal memory',
  knowledge: 'Knowledge / reference memory',
});

module.exports = { MEMORY_TYPES, MEMORY_LABELS };
