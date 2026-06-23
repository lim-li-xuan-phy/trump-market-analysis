#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <libpq-fe.h>
#include <map>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

namespace fs = std::filesystem;

// Structures
struct TradeRecord {
  std::string timestamp;
  std::string message_snippet;
  std::string topic;
  double sentiment_score;
  int signal; // 1 = Long, -1 = Short, 0 = Hold
  double gross_return;
  double net_return;
  double equity;
  double drawdown;
};

// Convert parsed timestamp to seconds since Unix Epoch.
long long timestamp_to_s(int year, int month, int day, int hour, int min,
                         int sec) {
  static const int days_in_month[] = {31, 28, 31, 30, 31, 30,
                                      31, 31, 30, 31, 30, 31};

  int leap_days = 0;
  for (int y = 1970; y < year; ++y) {
    if ((y % 4 == 0 && y % 100 != 0) || (y % 400 == 0)) {
      leap_days++;
    }
  }

  long long days = (year - 1970) * 365 + leap_days;
  for (int m = 0; m < month - 1; ++m) {
    if (m == 1 && ((year % 4 == 0 && year % 100 != 0) || (year % 400 == 0))) {
      days += 29;
    } else {
      days += days_in_month[m];
    }
  }
  days += day - 1;

  return days * 86400LL + hour * 3600LL + min * 60LL + sec;
}

// Converts "YYYY-MM-DD HH:MM:SS" to milliseconds since Unix Epoch
long long utc_to_ms(const std::string &ts_str) {
  int year, month, day, hour = 0, min = 0, sec = 0;
  if (sscanf(ts_str.c_str(), "%d-%d-%d %d:%d:%d", &year, &month, &day, &hour,
             &min, &sec) < 3) {
    return -1;
  }
  return timestamp_to_s(year, month, day, hour, min, sec) * 1000LL;
}

std::string trim(const std::string &str) {
  std::string s = str;
  s.erase(std::remove(s.begin(), s.end(), '\r'), s.end());
  s.erase(std::remove(s.begin(), s.end(), '\n'), s.end());
  s.erase(std::remove(s.begin(), s.end(), '"'), s.end());
  size_t first = s.find_first_not_of(" \t");
  if (first == std::string::npos)
    return "";
  size_t last = s.find_last_not_of(" \t");
  return s.substr(first, (last - first + 1));
}

std::unordered_map<std::string, std::string> load_env_file() {
  std::unordered_map<std::string, std::string> env;
  std::ifstream file("src/.env");
  if (!file.is_open()) {
    return env;
  }
  std::string line;
  while (std::getline(file, line)) {
    // Remove comments
    size_t comment_pos = line.find('#');
    if (comment_pos != std::string::npos) {
      line = line.substr(0, comment_pos);
    }

    // Find key=value
    size_t eq_pos = line.find('=');
    if (eq_pos == std::string::npos) {
      continue;
    }
    std::string key = line.substr(0, eq_pos);
    std::string value = line.substr(eq_pos + 1);

    // Helper to trim spaces and quotes
    auto trim_str = [](std::string &s) {
      s.erase(0, s.find_first_not_of(" \t\r\n\"'"));
      size_t last = s.find_last_not_of(" \t\r\n\"'");
      if (last != std::string::npos) {
        s.erase(last + 1);
      } else {
        s.clear();
      }
    };
    trim_str(key);
    trim_str(value);
    if (!key.empty()) {
      env[key] = value;
    }
  }
  return env;
}

PGconn *connect_db() {
  std::unordered_map<std::string, std::string> env = load_env_file();
  if (env.empty()) {
    std::cerr << "Error: Could not open src/.env file.\n";
    return nullptr;
  }

  std::string host = env["DB_HOST"];
  std::string port = env["DB_PORT"];
  std::string dbname = env["DB_NAME"];
  std::string user = env["DB_USER"];
  std::string password = env["DB_PASSWORD"];

  std::vector<std::string> parts;
  if (!host.empty())
    parts.push_back("host=" + host);
  if (!port.empty())
    parts.push_back("port=" + port);
  if (!dbname.empty())
    parts.push_back("dbname=" + dbname);
  if (!user.empty())
    parts.push_back("user=" + user);
  if (!password.empty())
    parts.push_back("password=" + password);

  if (parts.empty()) {
    std::cerr
        << "Error: No database connection details found in src/.env file.\n";
    return nullptr;
  }

  std::ostringstream oss;
  for (size_t i = 0; i < parts.size(); ++i) {
    oss << parts[i] << (i + 1 < parts.size() ? " " : "");
  }
  std::string conninfo = oss.str();

  PGconn *conn = PQconnectdb(conninfo.c_str());
  if (PQstatus(conn) != CONNECTION_OK) {
    std::cerr << "Connection to database failed: " << PQerrorMessage(conn)
              << std::endl;
    PQfinish(conn);
    return nullptr;
  }
  return conn;
}

int main(int argc, char *argv[]) {
  std::string topic_filter = "All";
  std::string asset = "ES";
  std::string horizon = "1d";
  double threshold = 0.05;
  double cost_bps = 5.0;
  double initial_capital = 10000.0;
  bool reversal_mode = false;
  bool print_trades = false;

  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    if (arg == "--topic" && i + 1 < argc) {
      topic_filter = argv[++i];
    } else if (arg == "--asset" && i + 1 < argc) {
      asset = argv[++i];
    } else if (arg == "--horizon" && i + 1 < argc) {
      horizon = argv[++i];
    } else if (arg == "--threshold" && i + 1 < argc) {
      threshold = std::stod(argv[++i]);
    } else if (arg == "--cost" && i + 1 < argc) {
      cost_bps = std::stod(argv[++i]);
    } else if (arg == "--capital" && i + 1 < argc) {
      initial_capital = std::stod(argv[++i]);
    } else if (arg == "--reversal") {
      reversal_mode = true;
    } else if (arg == "--print-trades") {
      print_trades = true;
    } else if (arg == "--help" || arg == "-h") {
      std::cout
          << "Usage: backtester.exe [options]\n"
          << "Options:\n"
          << "  --topic <topic>       Filter by topic or 'All' (default: All)\n"
          << "  --asset <name>        Asset to trade (default: ES)\n"
          << "  --horizon <time>      Holding horizon (default: 1d)\n"
          << "  --threshold <val>     Sentiment threshold to enter trade "
             "(default: 0.05)\n"
          << "  --cost <bps>          Transaction costs in basis points per "
             "trade (default: 5.0)\n"
          << "  --capital <val>       Starting balance (default: 10000.0)\n"
          << "  --reversal            Run in sentiment-reversal mode\n"
          << "  --print-trades        Print trade details to stdout\n"
          << "  --help, -h            Show this help menu\n";
      return 0;
    }
  }

  std::cout << "==================================================\n";
  std::cout << "          TRUMP MARKET ANALYSIS BACKTESTER\n";
  std::cout << "==================================================\n";
  std::cout << "Target Asset:     " << asset << "\n";
  std::cout << "Holding Horizon:  " << horizon << "\n";
  std::cout << "Filter Topic:     " << topic_filter << "\n";
  std::cout << "Sentiment Thresh: " << threshold << "\n";
  std::cout << "Trans. Cost Bps:  " << cost_bps << " bps ("
            << (cost_bps / 10000.0) << ")\n";
  std::cout << "Starting Capital: $" << std::fixed << std::setprecision(2)
            << initial_capital << "\n";
  std::cout << "Strategy Mode:    "
            << (reversal_mode ? "Sentiment Reversal" : "Sentiment Directional")
            << "\n";
  std::cout << "==================================================\n\n";

  PGconn *conn = connect_db();
  if (!conn) {
    return 1;
  }

  std::string return_col_name = "return_" + horizon + "_" + asset;
  std::cout << "Loading dataset from PostgreSQL final_dataset table...\n";

  std::string dataset_query;
  if (topic_filter == "All") {
    dataset_query =
        "SELECT timestamp_utc, message_snippet, topic, sentiment_score, \"" +
        return_col_name + "\" FROM final_dataset ORDER BY timestamp_utc;";
  } else {
    dataset_query =
        "SELECT timestamp_utc, message_snippet, topic, sentiment_score, \"" +
        return_col_name + "\" FROM final_dataset WHERE topic = '" +
        topic_filter + "' ORDER BY timestamp_utc;";
  }

  PGresult *res_data = PQexec(conn, dataset_query.c_str());
  if (PQresultStatus(res_data) != PGRES_TUPLES_OK) {
    std::cerr << "Error loading dataset: " << PQerrorMessage(conn) << "\n";
    PQclear(res_data);
    PQfinish(conn);
    return 1;
  }

  int num_rows = PQntuples(res_data);
  std::cout << "Total rows parsed from database: " << num_rows << "\n";

  double equity = initial_capital;
  double peak_equity = initial_capital;
  double max_drawdown = 0.0;
  long long first_timestamp_ms = -1;
  long long last_timestamp_ms = -1;

  std::vector<TradeRecord> trades;
  double cost_pct = cost_bps / 10000.0;

  for (int i = 0; i < num_rows; ++i) {
    std::string timestamp = PQgetvalue(res_data, i, 0);
    if (timestamp.find('.') != std::string::npos) {
      timestamp = timestamp.substr(0, timestamp.find('.'));
    }
    std::string snippet = PQgetvalue(res_data, i, 1);
    std::string topic = trim(PQgetvalue(res_data, i, 2));
    std::string sent_str = PQgetvalue(res_data, i, 3);
    std::string ret_str = PQgetvalue(res_data, i, 4);

    if (PQgetisnull(res_data, i, 3) || PQgetisnull(res_data, i, 4) ||
        sent_str.empty() || ret_str.empty()) {
      continue;
    }

    double sentiment = 0.0;
    double raw_return = 0.0;
    try {
      sentiment = std::stod(sent_str);
      raw_return = std::stod(ret_str);
    } catch (...) {
      continue;
    }

    int signal = 0;
    if (sentiment > threshold) {
      signal = reversal_mode ? -1 : 1;
    } else if (sentiment < -threshold) {
      signal = reversal_mode ? 1 : -1;
    }

    if (signal == 0) {
      continue;
    }

    long long ts_ms = utc_to_ms(timestamp);
    if (ts_ms != -1) {
      if (first_timestamp_ms == -1)
        first_timestamp_ms = ts_ms;
      last_timestamp_ms = ts_ms;
    }

    double gross_return = raw_return * signal;
    double net_return = gross_return - cost_pct;

    equity = equity * (1.0 + net_return);
    if (equity < 0.0)
      equity = 0.0;

    if (equity > peak_equity) {
      peak_equity = equity;
    }
    double current_drawdown = (peak_equity - equity) / peak_equity;
    if (current_drawdown > max_drawdown) {
      max_drawdown = current_drawdown;
    }

    TradeRecord trade;
    trade.timestamp = timestamp;
    trade.message_snippet = snippet;
    trade.topic = topic;
    trade.sentiment_score = sentiment;
    trade.signal = signal;
    trade.gross_return = gross_return;
    trade.net_return = net_return;
    trade.equity = equity;
    trade.drawdown = current_drawdown;

    trades.push_back(trade);
  }

  PQclear(res_data);

  if (trades.empty()) {
    std::cout
        << "No trades were generated with the current parameter settings.\n";
    PQfinish(conn);
    return 0;
  }

  // Calculate stats
  size_t total_trades = trades.size();
  size_t winning_trades = 0;
  double sum_net_returns = 0.0;
  std::vector<double> net_returns_list;

  for (const auto &t : trades) {
    if (t.net_return > 0.0) {
      winning_trades++;
    }
    sum_net_returns += t.net_return;
    net_returns_list.push_back(t.net_return);
  }

  double win_rate = (double)winning_trades / total_trades;
  double mean_return = sum_net_returns / total_trades;

  double variance = 0.0;
  for (double r : net_returns_list) {
    variance += (r - mean_return) * (r - mean_return);
  }
  double std_dev =
      (total_trades > 1) ? std::sqrt(variance / (total_trades - 1)) : 0.0;

  double total_years = 1.0;
  if (first_timestamp_ms != -1 && last_timestamp_ms != -1 &&
      last_timestamp_ms > first_timestamp_ms) {
    double total_days =
        (last_timestamp_ms - first_timestamp_ms) / (1000.0 * 60 * 60 * 24);
    total_years = total_days / 365.25;
    if (total_years < 0.01)
      total_years = 0.01;
  }

  double total_return_pct = (equity - initial_capital) / initial_capital;
  double annualized_return_pct =
      std::pow(equity / initial_capital, 1.0 / total_years) - 1.0;

  double trades_per_year = (double)total_trades / total_years;
  double sharpe_ratio = 0.0;
  if (std_dev > 1e-8) {
    sharpe_ratio = (mean_return / std_dev) * std::sqrt(trades_per_year);
  }

  // Print results
  std::cout << "\n==================================================\n";
  std::cout << "                BACKTEST RESULTS\n";
  std::cout << "==================================================\n";
  std::cout << "Total Trades:       " << total_trades << "\n";
  std::cout << "Winning Trades:     " << winning_trades << "\n";
  std::cout << "Losing Trades:      " << (total_trades - winning_trades)
            << "\n";
  std::cout << "Win Rate:           " << std::fixed << std::setprecision(2)
            << (win_rate * 100.0) << "%\n";
  std::cout << "Initial Capital:    $" << std::fixed << std::setprecision(2)
            << initial_capital << "\n";
  std::cout << "Final Equity:       $" << std::fixed << std::setprecision(2)
            << equity << "\n";
  std::cout << "Total Profit/Loss:  $" << std::fixed << std::setprecision(2)
            << (equity - initial_capital) << " (" << std::fixed
            << std::setprecision(2) << (total_return_pct * 100.0) << "%)\n";
  std::cout << "Annualized Return:  " << std::fixed << std::setprecision(2)
            << (annualized_return_pct * 100.0) << "%\n";
  std::cout << "Max Drawdown:       " << std::fixed << std::setprecision(2)
            << (max_drawdown * 100.0) << "%\n";
  std::cout << "Sharpe Ratio:       " << std::fixed << std::setprecision(3)
            << sharpe_ratio << "\n";
  std::cout << "Trades/Year (Avg):  " << std::fixed << std::setprecision(1)
            << trades_per_year << "\n";
  std::cout << "==================================================\n\n";

  // Detailed trades log
  if (print_trades) {
    std::cout << "DETAILED TRADES LOG (First 20 / Last 20):\n";
    std::cout << std::left << std::setw(20) << "Timestamp" << std::setw(15)
              << "Topic" << std::right << std::setw(8) << "Score"
              << std::setw(8) << "Signal" << std::setw(12) << "Net Ret"
              << std::setw(12) << "Equity" << "   " << "Message Snippet"
              << "\n";
    std::cout << std::string(100, '-') << "\n";

    size_t display_count = 20;
    for (size_t idx = 0; idx < total_trades; ++idx) {
      if (total_trades > 2 * display_count && idx >= display_count &&
          idx < total_trades - display_count) {
        if (idx == display_count) {
          std::cout << "... [ " << (total_trades - 2 * display_count)
                    << " trades hidden ] ...\n";
        }
        continue;
      }
      const auto &t = trades[idx];
      std::cout << std::left << std::setw(20) << t.timestamp.substr(0, 19)
                << std::setw(15) << t.topic.substr(0, 14) << std::right
                << std::setw(8) << std::fixed << std::setprecision(3)
                << t.sentiment_score << std::setw(8)
                << (t.signal == 1 ? "LONG" : "SHORT") << std::setw(12)
                << std::fixed << std::setprecision(5) << t.net_return
                << std::setw(12) << std::fixed << std::setprecision(2)
                << t.equity << "   " << t.message_snippet << "\n";
    }
    std::cout << "==================================================\n\n";
  }

  // Construct configname
  std::string clean_topic = topic_filter;
  std::replace(clean_topic.begin(), clean_topic.end(), '/', '_');
  std::string configname = "backtest_trades_" + asset + "_" + clean_topic +
                           "_" + horizon + (reversal_mode ? "_reversal" : "");

  // Create table if not exists
  PQexec(conn, "CREATE TABLE IF NOT EXISTS backtest_trades ("
               "configname TEXT, "
               "timestamp TIMESTAMP, "
               "message_snippet TEXT, "
               "topic TEXT, "
               "sentiment_score REAL, "
               "signal INTEGER, "
               "gross_return REAL, "
               "net_return REAL, "
               "equity REAL, "
               "drawdown REAL, "
               "PRIMARY KEY (configname, timestamp)"
               ");");

  // Save to PostgreSQL backtest_trades table inside transaction
  std::cout << "Saving " << trades.size()
            << " trades directly to database...\n";
  PQexec(conn, "BEGIN;");
  for (const auto &t : trades) {
    std::string clean_snippet = t.message_snippet;
    clean_snippet.erase(
        std::remove(clean_snippet.begin(), clean_snippet.end(), '\''),
        clean_snippet.end());
    clean_snippet.erase(
        std::remove(clean_snippet.begin(), clean_snippet.end(), '"'),
        clean_snippet.end());

    std::ostringstream sql;
    sql << "INSERT INTO backtest_trades ("
        << "configname, timestamp, message_snippet, topic, sentiment_score, "
           "signal, gross_return, net_return, equity, drawdown"
        << ") VALUES ("
        << "'" << configname << "', "
        << "'" << t.timestamp << "', "
        << "'" << clean_snippet << "', "
        << "'" << t.topic << "', " << t.sentiment_score << ", " << t.signal
        << ", " << t.gross_return << ", " << t.net_return << ", " << t.equity
        << ", " << t.drawdown
        << ") ON CONFLICT (configname, timestamp) DO UPDATE SET "
        << "message_snippet = EXCLUDED.message_snippet, "
        << "topic = EXCLUDED.topic, "
        << "sentiment_score = EXCLUDED.sentiment_score, "
        << "signal = EXCLUDED.signal, "
        << "gross_return = EXCLUDED.gross_return, "
        << "net_return = EXCLUDED.net_return, "
        << "equity = EXCLUDED.equity, "
        << "drawdown = EXCLUDED.drawdown;";

    PGresult *res_ins = PQexec(conn, sql.str().c_str());
    PQclear(res_ins);
  }
  PQexec(conn, "COMMIT;");

  PQfinish(conn);
  std::cout << "Detailed trades successfully saved to database table "
               "backtest_trades.\n";
  return 0;
}
