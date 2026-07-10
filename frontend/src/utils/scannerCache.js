/**
 * Scanner Results Cache Manager
 * 
 * Provides fast, cached access to scanner results across all pages
 * - Stores results in localStorage
 * - Returns cached data immediately
 * - Updates in background
 */

const CACHE_KEY = 'scanner_results_cache';
const CACHE_TIMESTAMP_KEY = 'scanner_results_timestamp';
const CACHE_DURATION = 60000; // 60 seconds

export const scannerCache = {
  /**
   * Get cached scanner results
   * Returns cached data immediately if available and fresh
   */
  get: () => {
    try {
      const cached = localStorage.getItem(CACHE_KEY);
      const timestamp = localStorage.getItem(CACHE_TIMESTAMP_KEY);
      
      if (cached && timestamp) {
        const age = Date.now() - parseInt(timestamp);
        return {
          data: JSON.parse(cached),
          age: age,
          isFresh: age < CACHE_DURATION,
          timestamp: parseInt(timestamp)
        };
      }
      
      return null;
    } catch (error) {
      console.error('Error reading scanner cache:', error);
      return null;
    }
  },

  /**
   * Set scanner results in cache
   */
  set: (results) => {
    try {
      localStorage.setItem(CACHE_KEY, JSON.stringify(results));
      localStorage.setItem(CACHE_TIMESTAMP_KEY, Date.now().toString());
      return true;
    } catch (error) {
      console.error('Error writing scanner cache:', error);
      return false;
    }
  },

  /**
   * Check if cache exists and is fresh
   */
  isFresh: () => {
    try {
      const timestamp = localStorage.getItem(CACHE_TIMESTAMP_KEY);
      if (!timestamp) return false;
      
      const age = Date.now() - parseInt(timestamp);
      return age < CACHE_DURATION;
    } catch {
      return false;
    }
  },

  /**
   * Clear cache
   */
  clear: () => {
    try {
      localStorage.removeItem(CACHE_KEY);
      localStorage.removeItem(CACHE_TIMESTAMP_KEY);
      return true;
    } catch (error) {
      console.error('Error clearing scanner cache:', error);
      return false;
    }
  },

  /**
   * Get cache age in seconds
   */
  getAge: () => {
    try {
      const timestamp = localStorage.getItem(CACHE_TIMESTAMP_KEY);
      if (!timestamp) return null;
      
      return Math.floor((Date.now() - parseInt(timestamp)) / 1000);
    } catch {
      return null;
    }
  }
};
