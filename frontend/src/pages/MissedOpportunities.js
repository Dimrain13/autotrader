import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { TrendingUp, TrendingDown, AlertCircle, CheckCircle, XCircle, Eye } from "lucide-react";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function MissedOpportunities() {
  const [opportunities, setOpportunities] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedDate, setSelectedDate] = useState('all');
  const [availableDates, setAvailableDates] = useState([]);

  const fetchData = async () => {
    try {
      const dateParam = selectedDate === 'all' ? '' : `?date=${selectedDate}`;
      const [oppsResponse, analyticsResponse] = await Promise.all([
        axios.get(`${API}/missed-opportunities${dateParam}`, { timeout: 15000 }),
        axios.get(`${API}/missed-opportunities/analytics`, { timeout: 15000 })
      ]);
      
      setOpportunities(oppsResponse.data.opportunities || []);
      setAnalytics(analyticsResponse.data);
      
      // Extract unique dates for filter
      const dates = [...new Set(oppsResponse.data.opportunities.map(o => o.date))].sort().reverse();
      setAvailableDates(dates);
    } catch (error) {
      console.error('Failed to fetch missed opportunities:', error);
      // Set empty state on error
      setOpportunities([]);
      setAnalytics({
        total_missed: 0,
        total_would_have_won: 0,
        total_would_have_lost: 0,
        total_potential_pnl: 0,
        by_criteria: {},
        by_date: {}
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [selectedDate]);

  const updateOpportunity = async (id, updates) => {
    try {
      await axios.put(`${API}/missed-opportunities/${id}`, updates);
      fetchData(); // Refresh data
    } catch (error) {
      console.error('Failed to update opportunity:', error);
    }
  };

  const getStatusBadge = (status) => {
    switch (status) {
      case 'would_have_won':
        return <span className="px-2 py-1 text-xs rounded-sm bg-[#00E599]/20 text-[#00E599] flex items-center gap-1"><CheckCircle size={12} /> Winner</span>;
      case 'would_have_lost':
        return <span className="px-2 py-1 text-xs rounded-sm bg-[#FF1A40]/20 text-[#FF1A40] flex items-center gap-1"><XCircle size={12} /> Loser</span>;
      case 'reviewed':
        return <span className="px-2 py-1 text-xs rounded-sm bg-[#2E5CFF]/20 text-[#2E5CFF] flex items-center gap-1"><Eye size={12} /> Reviewed</span>;
      default:
        return <span className="px-2 py-1 text-xs rounded-sm bg-neutral-700 text-neutral-300 flex items-center gap-1"><AlertCircle size={12} /> Not Reviewed</span>;
    }
  };

  const getCriteriaBadges = (criteria) => {
    if (!criteria) return null;
    return (
      <div className="flex flex-wrap gap-1">
        <span className={`px-1 py-0.5 text-xs rounded ${criteria.price_range ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'}`}>
          $2-20 {criteria.price_range ? '✓' : '✗'}
        </span>
        <span className={`px-1 py-0.5 text-xs rounded ${criteria.pct_change ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'}`}>
          +10% {criteria.pct_change ? '✓' : '✗'}
        </span>
        <span className={`px-1 py-0.5 text-xs rounded ${criteria.volume_ratio ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'}`}>
          5xVol {criteria.volume_ratio ? '✓' : '✗'}
        </span>
        <span className={`px-1 py-0.5 text-xs rounded ${criteria.float ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'}`}>
          Float {criteria.float ? '✓' : '✗'}
        </span>
        <span className={`px-1 py-0.5 text-xs rounded ${criteria.positive_news ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'}`}>
          News {criteria.positive_news ? '✓' : '✗'}
        </span>
      </div>
    );
  };

  const getMissedReasonBadge = (missed_criteria) => {
    if (!missed_criteria || missed_criteria.length === 0) {
      return <span className="text-xs text-green-400">All criteria met</span>;
    }
    return (
      <div className="flex flex-wrap gap-1">
        {missed_criteria.map((reason, idx) => (
          <span key={idx} className="px-1 py-0.5 text-xs rounded bg-red-900/30 text-red-400 border border-red-900/50">
            {reason}
          </span>
        ))}
      </div>
    );
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-neutral-500">Loading missed opportunities...</div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold" style={{ fontFamily: 'Unbounded, sans-serif' }}>
          Missed Opportunities
        </h1>
        <Select value={selectedDate} onValueChange={setSelectedDate}>
          <SelectTrigger className="w-[180px] bg-[#0A0A0A] border-white/10">
            <SelectValue placeholder="Filter by date" />
          </SelectTrigger>
          <SelectContent className="bg-[#1A1A1A] border-white/10">
            <SelectItem value="all">All Dates</SelectItem>
            {availableDates.map(date => (
              <SelectItem key={date} value={date}>{date}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Analytics Cards */}
      {analytics && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Card className="bg-[#0A0A0A] border-white/5">
            <CardContent className="p-4">
              <div className="text-xs text-neutral-500 mb-1">Total Missed</div>
              <div className="text-2xl font-bold text-white">{analytics.total_missed}</div>
            </CardContent>
          </Card>
          <Card className="bg-[#0A0A0A] border-white/5">
            <CardContent className="p-4">
              <div className="text-xs text-neutral-500 mb-1">Would Have Won</div>
              <div className="text-2xl font-bold text-[#00E599]">{analytics.total_would_have_won}</div>
            </CardContent>
          </Card>
          <Card className="bg-[#0A0A0A] border-white/5">
            <CardContent className="p-4">
              <div className="text-xs text-neutral-500 mb-1">Would Have Lost</div>
              <div className="text-2xl font-bold text-[#FF1A40]">{analytics.total_would_have_lost}</div>
            </CardContent>
          </Card>
          <Card className="bg-[#0A0A0A] border-white/5">
            <CardContent className="p-4">
              <div className="text-xs text-neutral-500 mb-1">Potential P&L</div>
              <div className={`text-2xl font-bold ${analytics.total_potential_pnl >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                ${analytics.total_potential_pnl?.toFixed(2) || '0.00'}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Opportunities List */}
      <Card className="bg-[#0A0A0A] border-white/5">
        <CardHeader>
          <CardTitle className="text-sm font-bold" style={{ fontFamily: 'Unbounded, sans-serif' }}>
            Scanner Results Not Traded
          </CardTitle>
        </CardHeader>
        <CardContent>
          {opportunities.length === 0 ? (
            <div className="text-center py-8 text-neutral-500">
              <AlertCircle className="mx-auto mb-2" size={32} />
              <p>No missed opportunities recorded yet.</p>
              <p className="text-xs mt-1">Opportunities will appear here when scanner finds stocks you don't trade.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/5 text-neutral-500 text-xs">
                    <th className="text-left py-2 px-2">Date</th>
                    <th className="text-left py-2 px-2">Symbol</th>
                    <th className="text-right py-2 px-2">Price</th>
                    <th className="text-right py-2 px-2">% Change</th>
                    <th className="text-right py-2 px-2">Rel Vol</th>
                    <th className="text-center py-2 px-2">Score</th>
                    <th className="text-left py-2 px-2">Criteria</th>
                    <th className="text-left py-2 px-2">Why Missed</th>
                    <th className="text-center py-2 px-2">Status</th>
                    <th className="text-center py-2 px-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {opportunities.map((opp) => (
                    <tr key={opp.id} className="border-b border-white/5 hover:bg-white/5">
                      <td className="py-2 px-2 text-neutral-400 text-xs">{opp.date}</td>
                      <td className="py-2 px-2 font-mono font-bold text-white">{opp.symbol}</td>
                      <td className="py-2 px-2 text-right font-mono">${opp.price_at_scan?.toFixed(2)}</td>
                      <td className={`py-2 px-2 text-right font-mono ${opp.pct_change >= 0 ? 'text-[#00E599]' : 'text-[#FF1A40]'}`}>
                        {opp.pct_change >= 0 ? '+' : ''}{opp.pct_change?.toFixed(1)}%
                      </td>
                      <td className="py-2 px-2 text-right font-mono text-[#2E5CFF]">{opp.rel_volume?.toFixed(1)}x</td>
                      <td className="py-2 px-2 text-center">
                        <span className={`px-2 py-1 text-xs rounded-sm font-bold ${
                          opp.criteria_count >= 4 ? 'bg-[#00E599]/20 text-[#00E599]' :
                          opp.criteria_count >= 3 ? 'bg-[#FFB800]/20 text-[#FFB800]' :
                          'bg-neutral-700 text-neutral-400'
                        }`}>
                          {opp.criteria_count || 0}/5
                        </span>
                      </td>
                      <td className="py-2 px-2">
                        {getCriteriaBadges(opp.criteria_met)}
                      </td>
                      <td className="py-2 px-2 max-w-[200px]">
                        {getMissedReasonBadge(opp.missed_criteria)}
                      </td>
                      <td className="py-2 px-2 text-center">{getStatusBadge(opp.status)}</td>
                      <td className="py-2 px-2 text-center">
                        <div className="flex gap-1 justify-center">
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-6 px-2 text-xs text-[#00E599] hover:bg-[#00E599]/20"
                            onClick={() => updateOpportunity(opp.id, { status: 'would_have_won' })}
                          >
                            Win
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-6 px-2 text-xs text-[#FF1A40] hover:bg-[#FF1A40]/20"
                            onClick={() => updateOpportunity(opp.id, { status: 'would_have_lost' })}
                          >
                            Loss
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Criteria Breakdown */}
      {analytics && analytics.by_criteria && Object.keys(analytics.by_criteria).length > 0 && (
        <Card className="bg-[#0A0A0A] border-white/5">
          <CardHeader>
            <CardTitle className="text-sm font-bold" style={{ fontFamily: 'Unbounded, sans-serif' }}>
              Missed by Criteria Met
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-5 gap-2">
              {[1, 2, 3, 4, 5].map(criteria => (
                <div key={criteria} className="text-center p-3 bg-[#121212] rounded-sm border border-white/5">
                  <div className="text-2xl font-bold text-[#2E5CFF]">{analytics.by_criteria[criteria] || 0}</div>
                  <div className="text-xs text-neutral-500">{criteria}/5 Criteria</div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
