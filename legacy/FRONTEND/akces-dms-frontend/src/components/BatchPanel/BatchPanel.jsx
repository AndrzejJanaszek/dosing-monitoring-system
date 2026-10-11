import React from "react";
import BatchDosageTable from "../BatchDosageTable/BatchDosageTable";
import styles from "./BatchPanel.module.css";

export default function BatchPanel() {
  const json = `
    {
  "batch": {
    "isActive": true,
    "timestampStart": "2025-09-17T08:00:00Z",
    "timestampEnd": null,
    "dosages": [
      {
        "id": 1,
        "valueStart": 15000,
        "valueEnd": 14500,
        "timestampStart": "2025-09-17T08:00:00Z",
        "timestampEnd": "2025-09-17T08:00:30Z",
        "isCollision": false,
        "valueDifference": -500,
        "collisionValueDifference": -500,
        "timeDifference": 30,
        "dosingSpeedFactor": -16.67,
        "tankId": 3,
        "tankName": "Cement 1",
        "type": "OUT"
      },
      {
        "id": 2,
        "valueStart": 14500,
        "valueEnd": 14000,
        "timestampStart": "2025-09-17T08:01:00Z",
        "timestampEnd": "2025-09-17T08:01:30Z",
        "isCollision": false,
        "valueDifference": -500,
        "collisionValueDifference": -499,
        "timeDifference": 30,
        "dosingSpeedFactor": -16.67,
        "tankId": 3,
        "tankName": "Cement 1",
        "type": "OUT"
      },
      {
        "id": 3,
        "valueStart": 14000,
        "valueEnd": 13500,
        "timestampStart": "2025-09-17T08:02:00Z",
        "timestampEnd": "2025-09-17T08:02:30Z",
        "isCollision": false,
        "valueDifference": -500,
        "collisionValueDifference": -500,
        "timeDifference": 30,
        "dosingSpeedFactor": -16.67,
        "tankId": 3,
        "tankName": "Cement 1",
        "type": "OUT"
      },
      {
        "id": 4,
        "valueStart": 13500,
        "valueEnd": 13000,
        "timestampStart": "2025-09-17T08:03:00Z",
        "timestampEnd": "2025-09-17T08:03:30Z",
        "isCollision": true,
        "valueDifference": -500,
        "collisionValueDifference": -480,
        "timeDifference": 30,
        "dosingSpeedFactor": 0,
        "tankId": 3,
        "tankName": "Cement 1",
        "type": "OUT"
      }
    ]
  }
}

  `;

  const { batch } = JSON.parse(json);
  const status = batch.isActive;
  const timestampStart = new Date(batch.timestampStart).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  const timestampEnd = batch.timestampEnd
    ? new Date(batch.timestampEnd).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      })
    : "--:--";
  const dosages = batch.dosages;
  const valueSum = dosages.reduce((sum, d) => sum + d.valueDifference, 0);
  const collisionValueSum = dosages.reduce(
    (sum, d) => sum + d.collisionValueDifference,
    0
  );

  return (
    <div className={styles.batchPanel}>
      <header className={styles.header}>
        <h1 className={styles.headerTitle}>GRUSZKA</h1>
        <div
          className={`${styles.statusIcon} ${
            status ? styles.statusIconGreen : styles.statusIconRed
          }`}
        ></div>
      </header>
      <div className={styles.timeContainer}>
        <div className={styles.timeStart}>{timestampStart}</div>
        <div className={styles.timeEnd}>{timestampEnd}</div>
      </div>
      <BatchDosageTable dosages={dosages}></BatchDosageTable>
      <div className={styles.summary}>
        <div className={styles.valueSum}>
          <span>Suma:</span>
          <span>{valueSum}</span>
        </div>
        <div className={styles.valueSum}>
          <span>Suma kolizyjna:</span>
          <span>{collisionValueSum}</span>
        </div>
      </div>
    </div>
  );
}
