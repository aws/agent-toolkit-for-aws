<!-- markdownlint-disable MD013 -->

# Reservation

Reservations give you exclusive access to a quantum device during a scheduled
time window. Compared with submitting tasks and hybrid jobs on demand, workloads
associated with the reservation do not wait in the regular device queue.

## Booking and cancelling a reservation

See [How to create a reservation](https://docs.aws.amazon.com/braket/latest/developerguide/braket-create-a-reservation.html)
for information on creating a reservation. Reservations must be requested
through the Amazon Braket console.

## Running quantum tasks during a reservation

See [Running quantum tasks during a reservation](https://docs.aws.amazon.com/braket/latest/developerguide/braket-run-quantum-task-with-reservation.html).

## Running hybrid jobs during a reservation

See [Running hybrid jobs during a reservation](https://docs.aws.amazon.com/braket/latest/developerguide/braket-run-hybrid-jobs-with-reservation.html).

## Device- and provider-specific behavior

Reservation-specific limits on task shots, gates, or other task features may vary
by device. When needed, check the device's `DeviceCapabilities` for
reservation-specific limits.

## References

- [Working with reservations](https://docs.aws.amazon.com/braket/latest/developerguide/braket-reservations.html)
- [How to create a reservation](https://docs.aws.amazon.com/braket/latest/developerguide/braket-create-a-reservation.html)
- [Running quantum tasks during a reservation](https://docs.aws.amazon.com/braket/latest/developerguide/braket-run-quantum-task-with-reservation.html)
- [Running hybrid jobs during a reservation](https://docs.aws.amazon.com/braket/latest/developerguide/braket-run-hybrid-jobs-with-reservation.html)
- [What happens at the end of your reservation](https://docs.aws.amazon.com/braket/latest/developerguide/braket-end-of-reservation.html)
- [Cancel or reschedule an existing reservation](https://docs.aws.amazon.com/braket/latest/developerguide/braket-cancel-reservation.html)
- [`DirectReservation` SDK API reference](https://amazon-braket-sdk-python.readthedocs.io/en/stable/_apidoc/braket.aws.direct_reservations.html)
