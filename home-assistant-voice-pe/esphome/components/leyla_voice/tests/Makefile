# Runs the tests of the pure logic on the computer, with address and undefined behaviour checks.
test: test_leyla_voice
	./test_leyla_voice

test_leyla_voice: test_leyla_voice.cpp ../gain.h ../message.h ../resample.h ../ring_buffer.h ../state_machine.h
	g++ -std=c++17 -Wall -Wextra -O1 -g -fsanitize=address,undefined -o $@ test_leyla_voice.cpp

clean:
	rm -f test_leyla_voice
