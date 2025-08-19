from random import randint

from locust import HttpUser, between, task


class QuickstartUser(HttpUser):
    wait_time = between(1, 2)

    @task
    def view_page(self):
        self.client.get("/svs/CMU-1.svs")

    @task
    def view_dzi(self):
        self.client.get("/svs/CMU-1.svs.dzi")

    @task
    def view_page_image(self):
        self.client.get("/svs/CMU-1.svs_files/10/0_0.jpeg")
        self.client.get("/svs/CMU-1.svs_files/10/1_0.jpeg")
        self.client.get("/svs/CMU-1.svs_files/10/0_1.jpeg")
        self.client.get("/svs/CMU-1.svs_files/10/1_1.jpeg")

    @task(3)
    def view_image(self):
        level = 16  # randint(0, 16)
        col = randint(0, 70)
        row = randint(0, 40)
        self.client.get(f"/svs/CMU-1.svs_files/{level}/{col}_{row}.jpeg")


# locust -f .\server\press_test.py --host=http://localhost:5000
# 100 users spawning 10 users per second for 5 minute, RPS is stable at 96+, seems OK
