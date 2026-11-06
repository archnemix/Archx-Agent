'use strict';

module.exports = {
  id: 'simple-chat',
  name: 'Simple chat',
  description: 'Plain text conversation with the selected model. No tools.',
  capabilities: {
    tools: false,
    textInput: true,
    textOutput: true,
  },
  prepareRequest({ messages }) {
    return { messages };
  },
};
