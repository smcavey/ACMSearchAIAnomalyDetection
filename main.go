package main

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"net/http"
	"time"

	"github.com/prometheus/client_golang/api"
	v1 "github.com/prometheus/client_golang/api/prometheus/v1"
	"github.com/prometheus/common/model"
	"gopkg.in/yaml.v3"
)

type Config struct {
	Services          map[string]string `yaml:"services"`
	Token             string            `yaml:"token"`
	PrometheusQueries map[string]string `yaml:"prometheus_queries"`
	Containers        []string          `yaml:"containers"`
	WindowSize        int               `yaml:"window_size"`
	ScrapeInterval    int64             `yaml:"scrape_interval"`
}

type MetricPayload struct {
	Service   string                        `json:"service"`
	Timestamp time.Time                     `json:"timestamp"`
	Metrics   map[string]map[string]float64 `json:"metrics"`
}

var metricsWindow []MetricPayload

type authTransport struct {
	Token     string
	Transport http.RoundTripper
}

var serviceRoutes map[string]string

var prometheusQueries map[string]string

// Periodically fetch and send metrics to anomaly detection service
func main() {
	cfg, err := loadConfig("config.yaml")
	if err != nil {
		log.Fatalf("Failed to load config: %s", err)
	}

	transport := &http.Transport{
		TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
	}
	client, err := api.NewClient(api.Config{
		Address: cfg.Services["prometheus"],
		RoundTripper: &authTransport{
			Token:     cfg.Token,
			Transport: transport,
		},
	})

	ticker := time.NewTicker(time.Duration(cfg.ScrapeInterval) * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			payload := collectMetrics(client, cfg.PrometheusQueries, cfg.Containers)
			if len(metricsWindow) == cfg.WindowSize {
				// remove oldest metrics from window
				metricsWindow = metricsWindow[1:]
			}
			metricsWindow = append(metricsWindow, payload)

			if len(metricsWindow) == cfg.WindowSize {
				err := sendToAnomalyDetectionService(metricsWindow)
				if err != nil {
					log.Printf("Error sending to LLM service: %v", err)
				}
			}
		}
	}
}

func sendToAnomalyDetectionService(window []MetricPayload) error {
	body, err := json.Marshal(window)
	if err != nil {
		return err
	}

	resp, err := http.Post("http://localhost:8082/analyze", "application/json", bytes.NewReader(body))
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	responseBody, _ := ioutil.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("service error: %s", responseBody)
	} else {
		fmt.Printf("\n%s\n", responseBody)
	}

	log.Println("Sent metrics to anomaly detection service service")
	return nil
}

func collectMetrics(client api.Client, queries map[string]string, containers []string) MetricPayload {
	v1api := v1.NewAPI(client)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	timestamp := time.Now()
	payload := MetricPayload{
		Timestamp: timestamp,
		Metrics:   make(map[string]map[string]float64),
	}

	for _, container := range containers {
		payload.Metrics[container] = make(map[string]float64)
		for baseMetric, template := range queries {
			query := fmt.Sprintf(template, container)
			result, _, err := v1api.Query(ctx, query, timestamp)
			if err != nil {
				log.Printf("Prometheus query error [%s]: %v", baseMetric, err)
				continue
			}

			if vector, ok := result.(model.Vector); ok && len(vector) > 0 {
				log.Printf("Prometheus query %s returned %v", query, vector[0].Value)
				payload.Metrics[container][baseMetric] = float64(vector[0].Value)
			}
		}
	}

	return payload
}

func (t *authTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	req.Header.Set("Authorization", "Bearer "+t.Token)
	return t.Transport.RoundTrip(req)
}

// Reads system config and important environment variables
func loadConfig(path string) (Config, error) {
	var cfg Config
	data, err := ioutil.ReadFile(path)
	if err != nil {
		return cfg, err
	}

	err = yaml.Unmarshal(data, &cfg)
	if err != nil {
		return cfg, err
	}

	return cfg, nil
}
