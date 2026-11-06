'use strict';

class ProxyError extends Error {
  constructor(message, status, upstream) {
    super(message);
    this.name = 'ProxyError';
    this.status = status || 502;
    this.upstream = upstream || null;
  }
}

module.exports = { ProxyError };
